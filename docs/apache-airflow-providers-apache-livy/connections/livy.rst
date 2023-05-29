 .. Licensed to the Apache Software Foundation (ASF) under one
    or more contributor license agreements.  See the NOTICE file
    distributed with this work for additional information
    regarding copyright ownership.  The ASF licenses this file
    to you under the Apache License, Version 2.0 (the
    "License"); you may not use this file except in compliance
    with the License.  You may obtain a copy of the License at

 ..   http://www.apache.org/licenses/LICENSE-2.0

 .. Unless required by applicable law or agreed to in writing,
    software distributed under the License is distributed on an
    "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
    KIND, either express or implied.  See the License for the
    specific language governing permissions and limitations
    under the License.

.. _howto/connection: livy

Apache Livy Connection
========================

The Apache Livy connection type configures a connection to Apache Livy via the ``requests`` Python package.


Default Connection IDs
----------------------

Livy hooks and operators use ``livy_default`` by default


Configuring the Connection
--------------------------

Login (optional)
    Specify the login for the http service you would like to connect too.

Password (optional)
    Specify the password for the http service you would like to connect too.

Host (optional)
    Specify the entire url or the base of the url for the service.

Port (optional)
    Specify a port number if applicable.

Schema (optional)
    Specify the service type etc: http/https.

Extras (optional)
    Specify headers in json format.
