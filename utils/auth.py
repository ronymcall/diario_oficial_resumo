import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta

from config import DB_PATH, get_config

_ITERACOES = 260_000
_DIAS_SESSAO_PADRAO = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_senha(senha: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), salt, _ITERACOES
    )
    return f"pbkdf2_sha256${_ITERACOES}${salt.hex()}${derivado.hex()}"


def _verificar_senha(senha: str, hash_salvo: str) -> bool:
    try:
        algoritmo, iteracoes_str, salt_hex, hash_hex = hash_salvo.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        iteracoes = int(iteracoes_str)
        salt = bytes.fromhex(salt_hex)
        esperado = bytes.fromhex(hash_hex)
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), salt, iteracoes
        )
        return hmac.compare_digest(calculado, esperado)
    except Exception:
        return False


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            nome TEXT NOT NULL,
            senha_hash TEXT NOT NULL,
            papel TEXT NOT NULL DEFAULT 'usuario',
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessoes (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expira_em TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    return conn


def criar_sessao_persistente(
    user_id: int, dias: int = _DIAS_SESSAO_PADRAO
) -> str:
    """Cria um token de sessão persistente no banco e retorna o token bruto."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    agora = datetime.now()
    expira = agora + timedelta(days=dias)

    conn = _get_conn()
    conn.execute(
        "DELETE FROM sessoes WHERE expira_em < ?", (agora.isoformat(),)
    )
    conn.execute(
        """
        INSERT INTO sessoes (token_hash, user_id, expira_em, criado_em)
        VALUES (?, ?, ?, ?)
        """,
        (token_hash, user_id, expira.isoformat(), agora.isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def validar_sessao_persistente(token: str | None) -> dict | None:
    """Valida o token salvo e retorna os dados do usuário caso esteja ativo e dentro da validade."""
    if not token or not isinstance(token, str):
        return None

    token_hash = _hash_token(token.strip())
    agora_iso = datetime.now().isoformat()

    conn = _get_conn()
    row = conn.execute(
        """
        SELECT u.id, u.username, u.nome, u.papel, u.ativo, s.expira_em
        FROM sessoes s
        JOIN usuarios u ON u.id = s.user_id
        WHERE s.token_hash = ?
        """,
        (token_hash,),
    ).fetchone()

    if not row:
        conn.close()
        return None

    user_id, username, nome, papel, ativo, expira_em = row
    if not ativo or expira_em < agora_iso:
        conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))
        conn.commit()
        conn.close()
        return None

    conn.close()
    return {
        "id": user_id,
        "username": username,
        "nome": nome,
        "papel": papel,
    }


def encerrar_sessao_persistente(token: str | None) -> None:
    if not token or not isinstance(token, str):
        return
    token_hash = _hash_token(token.strip())
    conn = _get_conn()
    conn.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))
    conn.commit()
    conn.close()


def garantir_admin_inicial() -> None:
    """Cria o usuário administrador inicial a partir do .env caso o banco não tenha admins ativos."""
    conn = _get_conn()
    tem_admin = conn.execute(
        "SELECT 1 FROM usuarios WHERE papel = 'admin' AND ativo = 1 LIMIT 1"
    ).fetchone()

    if not tem_admin:
        admin_user = (get_config("ADMIN_USERNAME") or "admin").strip().lower()
        admin_pass = (get_config("ADMIN_PASSWORD") or "admin123").strip()
        admin_nome = (get_config("ADMIN_NAME") or "Administrador").strip()

        existente = conn.execute(
            "SELECT id FROM usuarios WHERE username = ?", (admin_user,)
        ).fetchone()

        if existente:
            conn.execute(
                "UPDATE usuarios SET papel = 'admin', ativo = 1 WHERE id = ?",
                (existente[0],),
            )
        else:
            conn.execute(
                """
                INSERT INTO usuarios (username, nome, senha_hash, papel, ativo, criado_em)
                VALUES (?, ?, ?, 'admin', 1, ?)
                """,
                (
                    admin_user,
                    admin_nome,
                    _hash_senha(admin_pass),
                    datetime.now().strftime("%d/%m/%Y %H:%M"),
                ),
            )
        conn.commit()
    conn.close()


def autenticar_usuario(username: str, senha: str) -> dict | None:
    """Valida usuário e senha. Retorna dict com dados do usuário ou None."""
    garantir_admin_inicial()
    u = (username or "").strip().lower()
    if not u or not senha:
        return None

    conn = _get_conn()
    row = conn.execute(
        """
        SELECT id, username, nome, senha_hash, papel, ativo
        FROM usuarios
        WHERE username = ?
        """,
        (u,),
    ).fetchone()
    conn.close()

    if not row or not row[5]:
        return None

    if not _verificar_senha(senha, row[3]):
        return None

    return {
        "id": row[0],
        "username": row[1],
        "nome": row[2],
        "papel": row[4],
    }


def listar_usuarios() -> list[dict]:
    garantir_admin_inicial()
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id, username, nome, papel, ativo, criado_em
        FROM usuarios
        ORDER BY papel ASC, nome ASC
        """
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "username": r[1],
            "nome": r[2],
            "papel": r[3],
            "ativo": bool(r[4]),
            "criado_em": r[5],
        }
        for r in rows
    ]


def criar_usuario(
    username: str, nome: str, senha: str, papel: str = "usuario"
) -> tuple[bool, str]:
    u = (username or "").strip().lower()
    n = (nome or "").strip()
    if not u or len(u) < 3:
        return False, "O nome de usuário deve ter pelo menos 3 caracteres."
    if " " in u:
        return False, "O nome de usuário não pode conter espaços."
    if not n:
        return False, "Informe o nome completo do usuário."
    if not senha or len(senha) < 6:
        return False, "A senha deve ter pelo menos 6 caracteres."
    if papel not in ("admin", "usuario"):
        papel = "usuario"

    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO usuarios (username, nome, senha_hash, papel, ativo, criado_em)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                u,
                n,
                _hash_senha(senha),
                papel,
                datetime.now().strftime("%d/%m/%Y %H:%M"),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False, f"O usuário '{u}' já está cadastrado."
    conn.close()
    return True, f"Usuário '{u}' criado com sucesso."


def alterar_senha(
    username: str, nova_senha: str, senha_atual: str | None = None
) -> tuple[bool, str]:
    if not nova_senha or len(nova_senha) < 6:
        return False, "A nova senha deve ter pelo menos 6 caracteres."

    conn = _get_conn()
    row = conn.execute(
        "SELECT id, senha_hash FROM usuarios WHERE username = ?",
        (username.strip().lower(),),
    ).fetchone()
    if not row:
        conn.close()
        return False, "Usuário não encontrado."

    if senha_atual is not None and not _verificar_senha(senha_atual, row[1]):
        conn.close()
        return False, "A senha atual informada está incorreta."

    conn.execute(
        "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
        (_hash_senha(nova_senha), row[0]),
    )
    conn.commit()
    conn.close()
    return True, "Senha atualizada com sucesso."


def remover_usuario(username_alvo: str, username_logado: str) -> tuple[bool, str]:
    alvo = (username_alvo or "").strip().lower()
    atual = (username_logado or "").strip().lower()
    if alvo == atual:
        return False, "Você não pode excluir o seu próprio usuário."

    conn = _get_conn()
    row = conn.execute(
        "SELECT id, papel FROM usuarios WHERE username = ?", (alvo,)
    ).fetchone()
    if not row:
        conn.close()
        return False, "Usuário não encontrado."

    if row[1] == "admin":
        total_admins = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE papel = 'admin' AND ativo = 1"
        ).fetchone()[0]
        if total_admins <= 1:
            conn.close()
            return False, "Não é possível remover o único administrador do sistema."

    conn.execute("DELETE FROM sessoes WHERE user_id = ?", (row[0],))
    conn.execute("DELETE FROM usuarios WHERE id = ?", (row[0],))
    conn.commit()
    conn.close()
    return True, f"Usuário '{alvo}' removido."
