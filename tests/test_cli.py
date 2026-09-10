import unittest
from unittest.mock import patch

from marvel_mcp_narrator.interfaces.cli import _tool_injection, main, run_cli


class CLIToolInjectionTests(unittest.TestCase):
    def test_roll_command_returns_tool_payload(self):
        name, payload = _tool_injection('/roll --tn 10')
        self.assertEqual(name, 'roll_d616')
        self.assertIn('total', payload)
        self.assertEqual(payload['target_number'], 10)

    def test_rule_command_returns_reference(self):
        name, payload = _tool_injection('/rule edge')
        self.assertEqual(name, 'lookup_rule_reference')
        self.assertEqual(payload['rule_key'], 'edge')
        self.assertEqual(payload['title'], 'Edge')

    def test_roll_invalid_target_number_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'must be an integer'):
            _tool_injection('/roll --tn nope')


class CLIRunLoopTests(unittest.TestCase):
    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['hello narrator', 'exit'])
    def test_non_tool_message_is_sent_to_ollama(self, _mock_input, mock_chat):
        mock_chat.return_value = iter([{'message': {'content': 'hi'}}])

        run_cli(model='fake-model')

        call_messages = mock_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'user' and msg['content'] == 'hello narrator' for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['/roll', 'exit'])
    def test_roll_tool_injects_system_output_only(self, _mock_input, mock_chat):
        mock_chat.return_value = iter([{'message': {'content': 'narration'}}])

        run_cli(model='fake-model')

        call_messages = mock_chat.call_args.kwargs['messages']
        self.assertTrue(any(msg['role'] == 'user' and 'Tool output (roll_d616):' in msg['content'] for msg in call_messages))
        self.assertFalse(any(msg['role'] == 'user' and msg['content'] == '/roll' for msg in call_messages))

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['/roll --tn nope', 'exit'])
    def test_tool_error_does_not_call_ollama(self, _mock_input, mock_chat):
        run_cli(model='fake-model')
        mock_chat.assert_not_called()

    @patch('marvel_mcp_narrator.interfaces.cli.ollama.chat')
    @patch('builtins.input', side_effect=['hello narrator', 'hello narrator', 'exit'])
    def test_chat_error_rolls_back_pending_turn_messages(self, _mock_input, mock_chat):
        from ollama import RequestError

        def stream_once_then_error():
            yield {'message': {'content': 'ok'}}

        mock_chat.side_effect = [RequestError('offline'), stream_once_then_error()]

        run_cli(model='fake-model')

        second_messages = mock_chat.call_args_list[1].kwargs['messages']
        user_turns = [msg for msg in second_messages if msg['role'] == 'user' and msg['content'] == 'hello narrator']
        self.assertEqual(len(user_turns), 1)


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


if __name__ == '__main__':
    unittest.main()
