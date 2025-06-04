"""Tests for the envelope protocol implementation."""

import io
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from airflow.sdk.execution_time.task_runner import MessageEnvelope, CommsDecoder


class TestMessageEnvelope:
    """Test the MessageEnvelope model."""

    def test_envelope_creation(self):
        """Test basic envelope creation and serialization."""
        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=42)

        assert envelope.request_id
        assert envelope.content_length == 42

        # Test JSON serialization
        json_data = envelope.model_dump_json()
        parsed = json.loads(json_data)
        assert parsed["content_length"] == 42
        assert "request_id" in parsed

    def test_envelope_validation(self):
        """Test envelope validation with various inputs."""
        # Valid envelope
        valid_data = {"request_id": str(uuid.uuid4()), "content_length": 100}
        envelope = MessageEnvelope.model_validate(valid_data)
        assert envelope.content_length == 100

        # Test required fields
        with pytest.raises(ValueError):
            MessageEnvelope.model_validate({"request_id": "test"})  # Missing content_length

        with pytest.raises(ValueError):
            MessageEnvelope.model_validate({"content_length": 100})  # Missing request_id


class TestEnvelopeProtocolUTF8:
    """Test envelope protocol with UTF-8 characters."""

    def test_ascii_message(self):
        """Test envelope protocol with pure ASCII message."""
        message = {"type": "test", "data": "hello world"}
        payload_json = json.dumps(message)
        payload_bytes = payload_json.encode("utf-8")

        # Character count should equal byte count for ASCII
        assert len(payload_json) == len(payload_bytes)

        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=len(payload_bytes))

        # Simulate the protocol
        envelope_line = envelope.model_dump_json() + "\n"
        complete_message = envelope_line.encode("utf-8") + payload_bytes

        assert len(complete_message) > len(payload_bytes)

    def test_utf8_message(self):
        """Test envelope protocol with UTF-8 characters."""
        # Use raw UTF-8 string instead of json.dumps() which escapes UTF-8
        payload_json = '{"type": "test", "data": "Hello 世界 🚀"}'  # Raw UTF-8
        payload_bytes = payload_json.encode("utf-8")

        # Character count should be less than byte count for UTF-8
        assert len(payload_json) < len(payload_bytes)

        envelope = MessageEnvelope(
            request_id=str(uuid.uuid4()),
            content_length=len(payload_bytes),  # Must use byte count
        )

        # This should work correctly
        envelope_line = envelope.model_dump_json() + "\n"
        complete_message = envelope_line.encode("utf-8") + payload_bytes

        # Verify the envelope specifies correct byte count
        assert envelope.content_length == len(payload_bytes)

    def test_character_vs_byte_mismatch(self):
        """Test that character vs byte count mismatch is detected."""
        # Use raw UTF-8 strings, not JSON-encoded (which escapes the characters)
        payload_json = '{"type": "test", "data": "Hello 世界 🚀"}'  # Raw UTF-8 string

        char_count = len(payload_json)  # Character count
        byte_count = len(payload_json.encode("utf-8"))  # Byte count

        print(f"Characters: {char_count}, Bytes: {byte_count}")  # Debug info
        assert char_count != byte_count, (
            f"Test requires multi-byte UTF-8 characters (chars={char_count}, bytes={byte_count})"
        )

        # If we incorrectly use character count in envelope
        envelope_wrong = MessageEnvelope(
            request_id=str(uuid.uuid4()),
            content_length=char_count,  # Wrong - should be byte_count
        )

        # If we correctly use byte count in envelope
        envelope_correct = MessageEnvelope(
            request_id=str(uuid.uuid4()),
            content_length=byte_count,  # Correct
        )

        assert envelope_wrong.content_length < envelope_correct.content_length


class TestCommsDecoderEnvelopeProtocol:
    """Test CommsDecoder with envelope protocol."""

    def test_send_request_uses_byte_count(self):
        """Test that send_request correctly uses byte count in envelope."""
        # Mock setup
        mock_input = io.StringIO()
        mock_socket = MagicMock()

        decoder = CommsDecoder(input=mock_input)
        decoder.request_socket = mock_socket

        # Test message with UTF-8 characters
        from airflow.sdk.execution_time.comms import ToSupervisor
        # We need a concrete message type for testing
        # Let's create a simple test message structure

        test_message_data = {"type": "test", "data": "Hello 世界 🚀"}
        payload_json = json.dumps(test_message_data)
        payload_bytes = payload_json.encode("utf-8")

        # Create a mock message that behaves like a BaseModel
        mock_msg = MagicMock()
        mock_msg.model_dump_json.return_value = payload_json

        # Create a mock logger
        mock_log = MagicMock()

        # Call send_request
        decoder.send_request(log=mock_log, msg=mock_msg)

        # Verify write was called
        mock_socket.write.assert_called_once()
        written_data = mock_socket.write.call_args[0][0]

        # Parse the written data
        envelope_end = written_data.find(b"\n")
        envelope_bytes = written_data[:envelope_end]
        payload_part = written_data[envelope_end + 1 :]

        # Parse envelope
        envelope_data = json.loads(envelope_bytes.decode("utf-8"))
        assert envelope_data["content_length"] == len(payload_bytes)  # Should be byte count

        # Verify payload matches
        assert payload_part == payload_bytes

    def test_get_message_handles_utf8_correctly(self):
        """Test that get_message correctly handles UTF-8 characters with byte-accurate reading."""
        # Create test data with UTF-8 characters
        payload_json = '{"type": "StartupDetails", "data": "Hello 世界 🚀"}'
        payload_bytes = payload_json.encode("utf-8")

        print(f"Payload: {len(payload_json)} chars, {len(payload_bytes)} bytes")

        # Create envelope
        envelope = MessageEnvelope(
            request_id=str(uuid.uuid4()),
            content_length=len(payload_bytes),  # Byte count
        )
        envelope_line = envelope.model_dump_json() + "\n"

        # Combine envelope and payload
        complete_input = envelope_line + payload_json

        # Create mock input
        mock_input = io.StringIO(complete_input)
        decoder = CommsDecoder(input=mock_input)

        # Mock the decoder to avoid actual message parsing
        decoder.decoder = MagicMock()
        mock_result = {"type": "test"}
        decoder.decoder.validate_json.return_value = mock_result

        # The test: this should work without errors and read exactly the right number of bytes
        try:
            result = decoder.get_message()
            # Verify the decoder was called with the correct payload
            decoder.decoder.validate_json.assert_called_once_with(payload_json)
            assert result == mock_result
            print("✅ UTF-8 envelope protocol test passed")
        except Exception as e:
            print(f"❌ UTF-8 envelope protocol test failed: {e}")
            raise

    def test_get_message_character_byte_boundary(self):
        """Test edge case where character boundaries don't align with byte boundaries."""
        # This string has 3 characters but 12 bytes (each emoji is 4 bytes)
        payload_json = "🚀🌟⭐"  # 3 chars, 12 bytes total
        payload_bytes = payload_json.encode("utf-8")

        print(f"Test payload: {len(payload_json)} chars, {len(payload_bytes)} bytes")

        # Create envelope with exact byte count
        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=len(payload_bytes))
        envelope_line = envelope.model_dump_json() + "\n"

        # Combine envelope and payload
        complete_input = envelope_line + payload_json

        # Create mock input
        mock_input = io.StringIO(complete_input)
        decoder = CommsDecoder(input=mock_input)

        # Mock the decoder
        decoder.decoder = MagicMock()
        mock_result = {"type": "emoji_test"}
        decoder.decoder.validate_json.return_value = mock_result

        # This should work without errors
        try:
            result = decoder.get_message()
            # Verify the decoder received the exact payload
            decoder.decoder.validate_json.assert_called_once_with(payload_json)
            assert result == mock_result
            print("✅ Emoji boundary test passed")
        except Exception as e:
            print(f"❌ Emoji boundary test failed: {e}")
            raise


class TestLargeMessages:
    """Test envelope protocol with large messages."""

    def test_large_message_envelope(self):
        """Test envelope protocol with large messages (simulating large DAG serialization)."""
        # Create a large message (simulate 1MB+ DAG)
        large_data = "x" * (1024 * 1024)  # 1MB of data
        message = {"type": "large_dag", "serialized_dag": large_data}
        payload_json = json.dumps(message)
        payload_bytes = payload_json.encode("utf-8")

        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=len(payload_bytes))

        # Verify we can handle large content_length values
        assert envelope.content_length > 1024 * 1024

        # Test envelope JSON serialization
        envelope_json = envelope.model_dump_json()
        parsed_envelope = MessageEnvelope.model_validate_json(envelope_json)
        assert parsed_envelope.content_length == envelope.content_length


class TestFallbackBehavior:
    """Test fallback to line-based protocol."""

    def test_fallback_behavior_design(self):
        """Test the design considerations for fallback behavior."""
        # The fallback behavior in get_message tries to parse the first line
        # as both envelope and direct message. This test documents the expected behavior.

        # Case 1: Valid envelope format
        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=20)
        envelope_line = envelope.model_dump_json()

        # Should be parseable as envelope
        parsed_envelope = MessageEnvelope.model_validate_json(envelope_line)
        assert parsed_envelope.content_length == envelope.content_length

        # Case 2: Old line-based format
        old_format_message = {"type": "legacy", "data": "test"}
        old_format_line = json.dumps(old_format_message)

        # Should NOT be parseable as envelope (missing required fields)
        with pytest.raises(Exception):
            MessageEnvelope.model_validate_json(old_format_line)

        # But should be parseable as regular JSON
        parsed_legacy = json.loads(old_format_line)
        assert parsed_legacy["type"] == "legacy"


class TestErrorHandling:
    """Test error handling in envelope protocol."""

    def test_connection_closed(self):
        """Test handling of closed connections."""
        mock_input = io.StringIO("")  # Empty input simulates closed connection
        decoder = CommsDecoder(input=mock_input)

        with pytest.raises(EOFError, match="Connection closed"):
            decoder.get_message()

    def test_malformed_envelope(self):
        """Test handling of malformed envelope data."""
        malformed_data = "not json\n"
        mock_input = io.StringIO(malformed_data)
        decoder = CommsDecoder(input=mock_input)

        # Should fall back to line-based protocol and fail there too
        with pytest.raises(Exception):
            decoder.get_message()

    def test_incomplete_payload(self):
        """Test handling of incomplete payload data."""
        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=100)
        envelope_line = envelope.model_dump_json() + "\n"
        incomplete_payload = "short"  # Much shorter than expected 100 bytes

        mock_input = io.StringIO(envelope_line + incomplete_payload)
        decoder = CommsDecoder(input=mock_input)

        # The envelope protocol will fail due to incomplete payload, then fallback to line-based
        # protocol will fail because envelope header is not a valid discriminated union message
        from pydantic_core import ValidationError

        with pytest.raises(ValidationError, match="Unable to extract tag using discriminator"):
            decoder.get_message()


class TestSupervisorEnvelopeReader:
    """Test supervisor's envelope socket reader."""

    def test_supervisor_envelope_socket_reader_utf8(self):
        """Test that supervisor's envelope socket reader handles UTF-8 correctly."""
        from airflow.sdk.execution_time.supervisor import make_envelope_socket_reader
        from unittest.mock import MagicMock
        import socket

        # Create test data with UTF-8
        payload_json = '{"type": "test", "data": "Hello 世界 🚀"}'
        payload_bytes = payload_json.encode("utf-8")

        # Create envelope
        envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=len(payload_bytes))
        envelope_bytes = envelope.model_dump_json().encode("utf-8") + b"\n"

        # Complete message
        complete_message = envelope_bytes + payload_bytes

        print(f"Complete message size: {len(complete_message)} bytes")
        print(f"Payload: {len(payload_json)} chars, {len(payload_bytes)} bytes")

        # Create a generator to capture received messages
        received_messages = []

        def message_generator():
            while True:
                msg = yield
                received_messages.append(msg)

        # Create mock on_close
        on_close = MagicMock()

        # Create the envelope socket reader
        reader = make_envelope_socket_reader(message_generator(), on_close)

        # Create a mock socket that returns our test data
        mock_socket = MagicMock()

        # Simulate socket returning data in chunks
        # First call returns the complete message
        mock_socket.recv_into.side_effect = [
            len(complete_message),  # First call returns all data
            0,  # Second call returns 0 (EOF)
        ]

        # Mock the buffer behavior
        def mock_recv_into(buffer):
            if mock_socket.recv_into.call_count == 1:
                # Copy our test data into the buffer
                buffer[: len(complete_message)] = complete_message
                return len(complete_message)
            return 0

        mock_socket.recv_into.side_effect = mock_recv_into

        # Call the reader twice: once to process data, once to handle EOF
        result1 = reader(mock_socket)
        result2 = reader(mock_socket)

        # First call should return True (data processed)
        assert result1 is True
        # Second call should return False (EOF detected)
        assert result2 is False

        # Verify we received the correct payload
        assert len(received_messages) == 1
        assert received_messages[0] == payload_bytes

        print("✅ Supervisor envelope reader UTF-8 test passed")

    def test_supervisor_two_stage_reading(self):
        """Test the two-stage reading (envelope -> payload) in supervisor."""
        from airflow.sdk.execution_time.supervisor import make_envelope_socket_reader
        from unittest.mock import MagicMock

        # Create multiple messages to test state machine
        messages = ['{"msg": "first"}', '{"msg": "second", "data": "with UTF-8: 🚀"}']

        complete_data = b""
        for msg_json in messages:
            msg_bytes = msg_json.encode("utf-8")
            envelope = MessageEnvelope(request_id=str(uuid.uuid4()), content_length=len(msg_bytes))
            envelope_line = envelope.model_dump_json().encode("utf-8") + b"\n"
            complete_data += envelope_line + msg_bytes

        print(f"Total test data size: {len(complete_data)} bytes")

        # Create a generator to capture received messages
        received_messages = []

        def message_generator():
            while True:
                msg = yield
                received_messages.append(msg)

        on_close = MagicMock()
        reader = make_envelope_socket_reader(message_generator(), on_close)

        # Mock socket that returns all data at once
        mock_socket = MagicMock()

        def mock_recv_into(buffer):
            if mock_socket.recv_into.call_count == 1:
                buffer[: len(complete_data)] = complete_data
                return len(complete_data)
            return 0  # EOF on subsequent calls

        mock_socket.recv_into.side_effect = mock_recv_into

        # Process the data
        result = reader(mock_socket)
        assert result is True

        # Should have received both messages
        assert len(received_messages) == 2
        assert received_messages[0] == messages[0].encode("utf-8")
        assert received_messages[1] == messages[1].encode("utf-8")

        print("✅ Two-stage reading test passed")
