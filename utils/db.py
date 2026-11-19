import sqlite3
from typing import Any

from config import DB_PATH, get_config
from processor.extractor import Ato


class _PgCursorWrapper:
    def __init__(self, cur: Any):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PgConnWrapper:
    """Adaptador que permite usar a mesma sintaxe do sqlite3 no PostgreSQL (Supabase)."""

    is_postgres = True

    def __init__(self, dsn: str):
        import psycopg2

        self._conn = psycopg2.connect(dsn)

    def execute(self, sql: str, params: tuple | list = ()) -> _PgCursorWrapper:
        sql_pg = sql.replace("?", "%s").replace("IFNULL(", "COALESCE(")
        cur = self._conn.cursor()
        cur.execute(sql_pg, tuple(params))
        return _PgCursorWrapper(cur)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def abrir_conexao():
    """Abre conexão com o Supabase (PostgreSQL) se DATABASE_URL estiver definida, ou SQLite local."""
    db_url = get_config("DATABASE_URL").strip()
    if db_url:
        return _PgConnWrapper(db_url)
    conn = sqlite3.connect(str(DB_PATH))
    return conn


def _eh_postgres(conn: Any) -> bool:
    return getattr(conn, "is_postgres", False)


def _get_conn():
    conn = abrir_conexao()
    if _eh_postgres(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS atos (
                id SERIAL PRIMARY KEY,
                decreto TEXT,
                tipo TEXT,
                nome TEXT,
                cargo TEXT,
                orgao TEXT,
                data TEXT,
                detalhes TEXT,
                texto_original TEXT,
                edicao TEXT
            )
            """
        )
        conn.execute(
            "ALTER TABLE atos ADD COLUMN IF NOT EXISTS orgao TEXT"
        )
        conn.execute(
            "ALTER TABLE atos ADD COLUMN IF NOT EXISTS detalhes TEXT"
        )
        conn.execute(
            "ALTER TABLE atos ADD COLUMN IF NOT EXISTS texto_original TEXT"
        )
        conn.commit()
        return conn

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decreto TEXT,
            tipo TEXT,
            nome TEXT,
            cargo TEXT,
            orgao TEXT,
            data TEXT,
            edicao TEXT
        )
        """
    )
    colunas = {row[1] for row in conn.execute("PRAGMA table_info(atos)")}
    if "orgao" not in colunas:
        conn.execute("ALTER TABLE atos ADD COLUMN orgao TEXT")
    if "detalhes" not in colunas:
        conn.execute("ALTER TABLE atos ADD COLUMN detalhes TEXT")
    if "texto_original" not in colunas:
        conn.execute("ALTER TABLE atos ADD COLUMN texto_original TEXT")

    indices = {row[1] for row in conn.execute("PRAGMA index_list(atos)")}
    if "idx_atos_unico" in indices:
        definicao = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_atos_unico'"
        ).fetchone()
        if definicao and "cargo" in (definicao[0] or ""):
            conn.execute("DROP INDEX idx_atos_unico")
            indices.discard("idx_atos_unico")

    if "idx_atos_unico" not in indices:
        conn.execute(
            """
            DELETE FROM atos
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM atos
                GROUP BY IFNULL(edicao, ''), decreto, nome
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX idx_atos_unico ON atos (
                IFNULL(edicao, ''), decreto, nome
            )
            """
        )

    conn.commit()
    return conn


def _like_pattern(texto: str) -> str:
    for ch in ("!", "%", "_"):
        texto = texto.replace(ch, "!" + ch)
    return f"%{texto}%"


def salvar_atos(atos: list[Ato], edicao: str = "") -> None:
    conn = _get_conn()
    if edicao:
        conn.execute("DELETE FROM atos WHERE edicao = ?", (edicao,))
    for a in atos:
        conn.execute(
            """
            INSERT INTO atos
                (decreto, tipo, nome, cargo, orgao, data, detalhes, texto_original, edicao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                a.decreto,
                a.tipo,
                a.nome,
                a.cargo,
                a.orgao,
                a.data,
                a.detalhes,
                a.texto_original,
                edicao,
            ),
        )
    conn.commit()
    conn.close()


def carregar_atos(
    tipo: str | None = None,
    busca: str | None = None,
    orgao: str | None = None,
    edicao: str | None = None,
) -> list[dict]:
    conn = _get_conn()
    query = "SELECT decreto, tipo, nome, cargo, orgao, data, detalhes, texto_original, edicao FROM atos WHERE 1=1"
    params: list[str] = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if orgao:
        query += " AND orgao = ?"
        params.append(orgao)
    if edicao:
        query += " AND edicao = ?"
        params.append(edicao)
    if busca:
        padrao = _like_pattern(busca)
        query += (
            " AND (nome LIKE ? ESCAPE '!'"
            " OR IFNULL(cargo, '') LIKE ? ESCAPE '!'"
            " OR IFNULL(orgao, '') LIKE ? ESCAPE '!'"
            " OR IFNULL(detalhes, '') LIKE ? ESCAPE '!'"
            " OR IFNULL(decreto, '') LIKE ? ESCAPE '!')"
        )
        params.extend([padrao, padrao, padrao, padrao, padrao])
    query += " ORDER BY id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [
        {
            "decreto": r[0],
            "tipo": r[1],
            "nome": r[2],
            "cargo": r[3],
            "orgao": r[4],
            "data": r[5],
            "detalhes": r[6],
            "texto_original": r[7],
            "edicao": r[8],
        }
        for r in rows
    ]


def listar_opcoes_historico() -> dict[str, list[str]]:
    conn = _get_conn()
    edicoes = [
        r[0]
        for r in conn.execute(
            """
            SELECT edicao
            FROM atos
            WHERE edicao IS NOT NULL AND TRIM(edicao) != ''
            GROUP BY edicao
            ORDER BY MAX(id) DESC
            LIMIT 200
            """
        ).fetchall()
    ]
    orgaos = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT orgao
            FROM atos
            WHERE orgao IS NOT NULL AND TRIM(orgao) != ''
            ORDER BY orgao ASC
            LIMIT 500
            """
        ).fetchall()
    ]
    conn.close()
    return {"edicoes": edicoes, "orgaos": orgaos}


def carregar_atos_edicao(edicao: str) -> list[Ato]:
    registros = carregar_atos(edicao=edicao)
    return [
        Ato(
            decreto=r["decreto"],
            tipo=r["tipo"],
            nome=r["nome"],
            cargo=r["cargo"],
            orgao=r["orgao"],
            data=r["data"],
            detalhes=r.get("detalhes"),
            texto_original=r.get("texto_original"),
        )
        for r in reversed(registros)
    ]


def resumo_edicoes_recentes(limite: int = 12) -> list[dict]:
    """Retorna o resumo quantitativo das últimas edições (da mais antiga para a mais recente)."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT
            edicao,
            COUNT(*) AS total,
            SUM(CASE WHEN tipo = 'nomeação' THEN 1 ELSE 0 END) AS nomeacoes,
            SUM(CASE WHEN tipo = 'exoneração' THEN 1 ELSE 0 END) AS exoneracoes,
            SUM(CASE WHEN tipo = 'outro' THEN 1 ELSE 0 END) AS outros,
            COUNT(DISTINCT CASE WHEN orgao IS NOT NULL AND TRIM(orgao) != '' THEN orgao END) AS orgaos
        FROM atos
        WHERE edicao IS NOT NULL AND TRIM(edicao) != ''
        GROUP BY edicao
        ORDER BY MAX(id) DESC
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    conn.close()
    return [
        {
            "edicao": r[0],
            "total": int(r[1] or 0),
            "nomeacoes": int(r[2] or 0),
            "exoneracoes": int(r[3] or 0),
            "outros": int(r[4] or 0),
            "orgaos": int(r[5] or 0),
        }
        for r in reversed(rows)
    ]
