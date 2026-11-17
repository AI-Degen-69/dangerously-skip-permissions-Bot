"""Startup must not create competing mirror state after a failed migration."""

import io
import unittest
from unittest.mock import patch

from bot import api, live_paper


class MirrorStartupTests(unittest.TestCase):
    def test_api_stops_before_sampler_or_server_on_error(self):
        with patch("sys.argv", ["api.py"]), \
             patch.object(api, "migrate_windows_mirror", return_value="error"), \
             patch.object(api, "start_background_sampler") as sampler, \
             patch.object(api, "QuietThreadingHTTPServer") as server, \
             patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                api.main()
        self.assertEqual(error.exception.code, 1)
        sampler.assert_not_called()
        server.assert_not_called()

    def test_live_paper_stops_before_session_on_error(self):
        with patch("sys.argv", ["live_paper.py"]), \
             patch.object(live_paper, "migrate_windows_mirror", return_value="error"), \
             patch.object(live_paper, "PublicClient") as client, \
             patch.object(live_paper, "init_run_session") as session, \
             patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                live_paper.main()
        self.assertEqual(error.exception.code, 1)
        client.assert_not_called()
        session.assert_not_called()

    def test_api_continues_for_non_error_results(self):
        for status in ("moved", "absent", "both-exist"):
            with self.subTest(status=status), \
                 patch("sys.argv", ["api.py", "--port", "8790"]), \
                 patch.object(api, "migrate_windows_mirror", return_value=status), \
                 patch.object(api, "start_background_sampler") as sampler, \
                 patch.object(api, "QuietThreadingHTTPServer") as server, \
                 patch("sys.stdout", new_callable=io.StringIO):
                api.main()
                sampler.assert_called_once_with()
                server.assert_called_once_with(("127.0.0.1", 8790), api.Handler)
                server.return_value.serve_forever.assert_called_once_with()

    def test_live_paper_continues_to_session_for_non_error_results(self):
        for status in ("moved", "absent", "both-exist"):
            with self.subTest(status=status), \
                 patch("sys.argv", ["live_paper.py"]), \
                 patch.object(live_paper, "migrate_windows_mirror", return_value=status), \
                 patch.object(live_paper, "PublicClient"), \
                 patch.object(live_paper, "init_run_session", side_effect=InterruptedError) as session:
                # Stop at the session boundary to avoid trading or writing runtime state.
                with self.assertRaises(InterruptedError):
                    live_paper.main()
                session.assert_called_once_with(run_id=None, label="msr_v2")
