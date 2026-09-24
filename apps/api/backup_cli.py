"""Supported terminal interface for encrypted local memory backups."""

from __future__ import annotations

import argparse
import getpass
import hmac
import logging
import sys
from pathlib import Path

from backup_recovery import (
    BackupError,
    create_backup,
    default_backup_directory,
    default_restore_directory,
    restore_backup,
)
from memory_store import default_database_path

logger = logging.getLogger(__name__)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message  # argparse's text can echo a supplied secret argument.
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: argumentos inválidos\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Backup cifrado local da memória SQLite do JARVIS."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="criar um backup cifrado do banco local")
    restore = commands.add_parser("restore", help="restaurar para um diretório novo e isolado")
    restore.add_argument("arquivo", help="nome do arquivo dentro da pasta privada de backups")
    return parser


def _prompt_passphrase(*, confirm: bool) -> str:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise BackupError("a senha só pode ser informada em um terminal interativo")
    try:
        passphrase = getpass.getpass("Senha do backup: ")
        if confirm:
            repeated = getpass.getpass("Repita a senha: ")
            if not hmac.compare_digest(passphrase, repeated):
                raise BackupError("as senhas informadas não coincidem")
        return passphrase
    except (EOFError, KeyboardInterrupt) as exc:
        raise BackupError("operação cancelada") from exc


def run(arguments: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(arguments)
    database = default_database_path()
    try:
        if options.command == "backup":
            passphrase = _prompt_passphrase(confirm=True)
            result = create_backup(database, default_backup_directory(database), passphrase)
            print(f"Backup cifrado criado: {result.name}")
            return 0

        filename = options.arquivo
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or filename.startswith(".")
            or not filename.startswith("jarvis-backup-v1-")
            or not filename.endswith(".jvb")
        ):
            raise BackupError("informe apenas o nome de um backup JARVIS válido")
        passphrase = _prompt_passphrase(confirm=False)
        source = default_backup_directory(database) / filename
        result = restore_backup(source, default_restore_directory(database), passphrase)
        print(f"Banco restaurado isoladamente em: {result.parent}")
        return 0
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - hide unexpected local paths and low-level details.
        logger.error("local backup command failed")
        print("não foi possível concluir a operação de backup/restauração", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
