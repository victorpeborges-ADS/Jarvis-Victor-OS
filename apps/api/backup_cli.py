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
    restore.add_argument(
        "--confirm-legacy-resurrection",
        action="store_true",
        help="confirmar que um backup antigo sem tombstones pode trazer de volta itens apagados",
    )
    activate = commands.add_parser("activate", help="ativar offline um backup de schema exato, com confirmação")
    activate.add_argument("--confirm-legacy-resurrection", action="store_true",
                          help="confirmar que conteúdo excluído pode voltar de backup sem ledger")
    activate.add_argument("arquivo", help="caminho absoluto do backup cifrado")
    activate.add_argument("--database", required=True, help="caminho absoluto e explícito do banco a substituir")
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
    try:
        if options.command == "activate":
            from restore_activation import activate, prepare_activation
            if not Path(options.database).is_absolute() or not Path(options.arquivo).is_absolute():
                raise BackupError("ativação exige caminhos absolutos explícitos")
            passphrase = _prompt_passphrase(confirm=False)
            if options.confirm_legacy_resurrection:
                print("Aviso: backup sem ledger pode trazer conteúdo excluído de volta.", file=sys.stderr)
            plan = prepare_activation(options.arquivo, options.database, passphrase,
                                      confirm_legacy_resurrection=options.confirm_legacy_resurrection)
            print(f"Destino a substituir: {plan.database}")
            print(f"SHA-256 do backup: {plan.archive_hash}")
            print(f"Manifest do schema/runtime: {plan.schema_hash}")
            print("O estado atual será substituído. Um rollback independente será preservado.")
            print("Automações restauradas ficarão pausadas até revisão e retomada explícita.")
            print(f"Para confirmar, digite exatamente: {plan.confirmation}")
            try:
                confirmation = input("> ")
            except (EOFError, KeyboardInterrupt) as exc:
                raise BackupError("operação cancelada") from exc
            rollback = activate(plan, confirmation)
            print(f"Ativação concluída. Rollback preservado em: {rollback}")
            return 0

        database = default_database_path()
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
        if options.confirm_legacy_resurrection:
            print(
                "Aviso: este backup pode não conter o registro de exclusões e pode restaurar itens apagados.",
                file=sys.stderr,
            )
        result = restore_backup(
            source,
            default_restore_directory(database),
            passphrase,
            confirm_legacy_resurrection=options.confirm_legacy_resurrection,
        )
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
