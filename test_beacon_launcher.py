import unittest
from unittest.mock import patch

from beacon import BeaconConfig, BeaconLauncher


class BeaconLauncherTests(unittest.TestCase):
    def setUp(self):
        self.launcher = BeaconLauncher(BeaconConfig())

    def test_launch_dashboard_uses_bun_server_ts(self):
        with patch("beacon.Path.exists", return_value=True), patch.object(self.launcher.pm, "spawn") as spawn:
            self.launcher._launch_dashboard()
        spawn.assert_called_once_with(["bun", "run", "server.ts"], name="dashboard")

    def test_launch_integration_uses_bun_for_typescript_entry(self):
        with patch("beacon.Path.exists", return_value=True), patch.object(self.launcher.pm, "spawn") as spawn:
            self.launcher._launch_integration("wildfire")
        self.assertEqual(spawn.call_args.args[0], ["bun", "run", "main.ts"])
        self.assertEqual(spawn.call_args.kwargs["name"], "mission")
        self.assertIn("env", spawn.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
