// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

package execution

import (
	"fmt"
	"log/slog"
	"net"
	"os"
	"strings"
	"sync"

	"github.com/apache/airflow/go-sdk/sdk"
)

// Serve is the main entry point for coordinator-mode execution.
// It parses --comm and --logs from os.Args, connects to both TCP sockets,
// reads the first message to determine the mode (DAG parsing or task execution),
// and handles the request.
//
// Usage:
//
//	./executable --comm=host:port --logs=host:port
func Serve(bundle *sdk.Bundle) {
	if err := ServeWithArgs(bundle, os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "execution error: %v\n", err)
		os.Exit(1)
	}
}

// ServeWithArgs is like Serve but accepts explicit arguments instead of os.Args.
func ServeWithArgs(bundle *sdk.Bundle, args []string) error {
	commAddr, logsAddr, err := parseArgs(args)
	if err != nil {
		return fmt.Errorf("parsing args: %w", err)
	}

	// Set up the log handler that will buffer until connected.
	logHandler := NewSocketLogHandler(nil, slog.LevelDebug)
	taskLogger := slog.New(logHandler)
	internalLogger := slog.New(logHandler)

	// Connect to both sockets concurrently.
	var commConn, logsConn net.Conn
	var commErr, logsErr error
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		commConn, commErr = net.Dial("tcp", commAddr)
	}()
	go func() {
		defer wg.Done()
		logsConn, logsErr = net.Dial("tcp", logsAddr)
	}()
	wg.Wait()

	if commErr != nil {
		return fmt.Errorf("connecting to comm socket %s: %w", commAddr, commErr)
	}
	defer commConn.Close()

	if logsErr != nil {
		return fmt.Errorf("connecting to logs socket %s: %w", logsAddr, logsErr)
	}
	defer logsConn.Close()

	// Connect the log handler to the logs socket — flushes any buffered messages.
	logHandler.Connect(logsConn)

	internalLogger.Debug("Connected", "comm", commAddr, "logs", logsAddr)

	// Create the comm channel.
	comm := NewCoordinatorComm(commConn, commConn, internalLogger)

	// Read the first message to determine execution mode.
	frame, err := comm.ReadMessage()
	if err != nil {
		return fmt.Errorf("reading initial message: %w", err)
	}

	// Dispatch based on the message type.
	if frame.Err != nil {
		errResp := decodeErrorResponse(frame.Err)
		if errResp != nil {
			return fmt.Errorf(
				"received error from supervisor: [%s] %v",
				errResp.Error,
				errResp.Detail,
			)
		}
	}

	body, err := decodeIncomingBody(frame.Body)
	if err != nil {
		return fmt.Errorf("decoding initial message: %w", err)
	}

	switch msg := body.(type) {
	case *DagFileParseRequest:
		internalLogger.Debug("DAG parsing mode", "file", msg.File)
		result := ParseDags(bundle, msg)
		if err := comm.SendRequest(frame.ID, result); err != nil {
			return fmt.Errorf("sending parse result: %w", err)
		}
		internalLogger.Debug("DAG parsing complete")

	case *StartupDetails:
		internalLogger.Debug("Task execution mode",
			"dag_id", msg.TI.DagID,
			"task_id", msg.TI.TaskID,
		)
		result := RunTask(bundle, msg, comm, taskLogger)
		if err := comm.SendRequest(frame.ID, result); err != nil {
			return fmt.Errorf("sending task result: %w", err)
		}
		internalLogger.Debug("Task execution complete")

	default:
		return fmt.Errorf("unexpected initial message type: %T", body)
	}

	return nil
}

// parseArgs extracts --comm and --logs addresses from command-line arguments.
func parseArgs(args []string) (commAddr, logsAddr string, err error) {
	for _, arg := range args {
		switch {
		case strings.HasPrefix(arg, "--comm="):
			commAddr = strings.TrimPrefix(arg, "--comm=")
		case strings.HasPrefix(arg, "--logs="):
			logsAddr = strings.TrimPrefix(arg, "--logs=")
		}
	}
	if commAddr == "" {
		return "", "", fmt.Errorf("missing --comm=host:port argument")
	}
	if logsAddr == "" {
		return "", "", fmt.Errorf("missing --logs=host:port argument")
	}
	return commAddr, logsAddr, nil
}
