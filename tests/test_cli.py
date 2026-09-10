import unittest
import tomllib
from pathlib import Path
from unittest.mock import patch

from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError
from marvel_mcp_narrator.interfaces.cli import _tool_injection, main, run_cli


class CLIToolInjectionTests(unittest.TestCase):
    def test_roll_command_returns_tool_payload(self):
        name, payload = _tool_injection('/roll --tn 10')
        self.assertEqual(name, 'resolve_d616_roll')
        self.assertIn('total', payload)
        self.assertEqual(payload['target_number'], 10)

    def test_rule_command_returns_search_results(self):
        name, payload = _tool_injection('/rule edge')
        self.assertEqual(name, 'lookup_rule')
        self.assertIn('Rulebook Search Results', payload)
        self.assertIn('Edges and Troubles', payload)

    def test_roll_invalid_target_number_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'must be a positive integer'):
            _tool_injection('/roll --tn nope')

    def test_roll_rejects_unexpected_positional_argument(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll foo')

    def test_roll_rejects_extra_argument_after_target_number(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --tn 10 extra')

    def test_roll_rejects_flag_as_target_number_value(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --tn --edge')

    def test_roll_rejects_negative_target_number(self):
        with self.assertRaisesRegex(ValueError, 'must be a positive integer'):
            _tool_injection('/roll --tn -1')

    def test_roll_rejects_zero_target_number(self):
        with self.assertRaisesRegex(ValueError, 'must be a positive integer'):
            _tool_injection('/roll --tn 0')

    def test_roll_accepts_plus_prefixed_target_number(self):
        name, payload = _tool_injection('/roll --tn +10')
        self.assertEqual(name, 'resolve_d616_roll')
        self.assertEqual(payload['target_number'], 10)

    def test_roll_rejects_duplicate_flags(self):
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --edge --edge')
        with self.assertRaisesRegex(ValueError, 'Usage: /roll'):
            _tool_injection('/roll --tn 10 --tn 20')

    def test_roll_edge_trouble_combo_raises_configuration_error(self):
        with self.assertRaises(D616ConfigurationError):
            _tool_injection('/roll --edge --trouble')


class CLIRunLoopTests(unittest.TestCase):
    class _FakeMessage:
        def __init__(self, content):
            self.content = content

    class _FakePacket:
        def __init__(self, content):
            self.message = CLIRunLoopTests._FakeMessage(content)

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_non_tool_message_is_sent_to_ollama(self, _mock_input, mock_chat):
        mock_chat.return_value = iter([{'message': {'content': 'hi'}}])

        run_cli(model='fake-model')

        call_messages = mock_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'user' and msg['content'] == 'hello narrator' for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_non_stream_object_response_is_handled(self, _mock_input, mock_chat):
        mock_chat.return_value = self._FakePacket('hi')
        run_cli(model='fake-model')
        mock_chat.assert_called_once()

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['/roll', 'exit'])
    def test_roll_tool_injects_system_output_only(self, _mock_input, mock_chat):
        mock_chat.return_value = iter([{'message': {'content': 'narration'}}])

        run_cli(model='fake-model')

        call_messages = mock_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'tool' and 'Tool output (resolve_d616_roll):' in msg['content'] for msg in call_messages))
        self.assertFalse(any(msg['role'] == 'user' and msg['content'] == '/roll' for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['/rule teleport', 'exit'])
    def test_rule_tool_injects_query_results(self, _mock_input, mock_chat):
        mock_chat.return_value = iter([{'message': {'content': 'narration'}}])

        run_cli(model='fake-model')

        call_messages = mock_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'tool' and 'Tool output (lookup_rule):' in msg['content'] for msg in call_messages))
        self.assertTrue(any(msg['role'] == 'tool' and 'Teleportation' in msg['content'] for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['/roll --tn nope', 'exit'])
    def test_tool_error_does_not_call_ollama(self, _mock_input, mock_chat):
        run_cli(model='fake-model')
        mock_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['/rule', 'exit'])
    def test_rule_usage_error_does_not_call_ollama(self, _mock_input, mock_chat):
        run_cli(model='fake-model')
        mock_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['hello narrator', 'hello narrator', 'exit'])
    def test_chat_error_rolls_back_pending_turn_messages(self, _mock_input, mock_chat):
        from ollama import RequestError

        def stream_once_then_error():
            yield {'message': {'content': 'ok'}}
            raise RequestError('stream dropped')

        mock_chat.side_effect = [stream_once_then_error(), stream_once_then_error()]

        run_cli(model='fake-model')

        second_messages = mock_chat.call_args_list[1].kwargs['messages']
        user_turns = [msg for msg in second_messages if msg['role'] == 'user' and msg['content'] == 'hello narrator']
        self.assertEqual(len(user_turns), 1)
        self.assertFalse(any(msg['role'] == 'assistant' and msg['content'] == 'ok' for msg in second_messages))


class CLIMainTests(unittest.TestCase):
    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli'])
    def test_main_uses_default_model(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(model='llama3.3')

    @patch('marvel_mcp_narrator.interfaces.cli.run_cli')
    @patch('sys.argv', ['cli', '--model', 'qwen2.5-coder'])
    def test_main_passes_custom_model(self, mock_run_cli):
        main()
        mock_run_cli.assert_called_once_with(model='qwen2.5-coder')


class PackagingEntryPointTests(unittest.TestCase):
    def test_pyproject_defines_cli_entrypoint(self):
        pyproject = Path(__file__).resolve().parent.parent / 'pyproject.toml'
        data = tomllib.loads(pyproject.read_text(encoding='utf-8'))
        self.assertEqual(
            data['project']['scripts']['marvel-narrator-cli'],
            'marvel_mcp_narrator.interfaces.cli:main',
        )


if __name__ == '__main__':
    unittest.main()
