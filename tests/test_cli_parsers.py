"""CLI argument contracts that must stay aligned across Horizon tools."""

from src.services.locales_cli import build_parser as locales_parser
from src.services.webhook_cli import build_parser as webhook_parser


def test_webhook_cli_accepts_custom_config_and_data_directory():
    args = webhook_parser().parse_args(["--data-dir", "/srv/state", "--config", "/etc/horizon/config.json"])

    assert args.data_dir == "/srv/state"
    assert args.config == "/etc/horizon/config.json"


def test_locales_cli_accepts_custom_config_and_data_directory():
    args = locales_parser().parse_args(["--data-dir", "/srv/state", "--config", "/etc/horizon/config.json"])

    assert args.data_dir == "/srv/state"
    assert args.config == "/etc/horizon/config.json"
