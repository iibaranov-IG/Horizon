"""Validate configured output locales without fetching news or calling an AI provider."""

import argparse
from pathlib import Path

from rich.console import Console

from ..ai.summarizer import DailySummarizer
from ..processing.profiles import ProfileRegistry
from ..storage.manager import StorageManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-d", "--data-dir", default="data", help="Directory for Horizon state (default: data)"
    )
    parser.add_argument(
        "-c", "--config", default=None, help="Path to config.json (default: <data-dir>/config.json)"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    console = Console()
    storage = StorageManager(data_dir=args.data_dir, config_path=args.config)
    config = storage.load_config()
    profiles = ProfileRegistry.load(
        Path(config.processing.profiles_dir),
        config.processing.default_profile,
        base_dir=storage.config_path.parent,
    )
    strict = config.ai.locale_mode == "production"
    summarizer = DailySummarizer(
        profile_names=profiles.names,
        locales=config.ai.locales,
        strict_locales=strict,
    )
    profiles.validate_output_languages(config.ai.languages, strict=strict)
    for language in config.ai.languages:
        summarizer.validate_locale_configuration(language)
    console.print("[green]Locale validation passed.[/green]")


if __name__ == "__main__":
    main()
