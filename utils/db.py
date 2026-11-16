import sqlite3

from config import DB_PATH
from processor.extractor import Ato


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
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
    """)
    colunas = {row[1] for row in conn.execute("PRAGMA table_info(atos)")}
    if "orgao" not in colunas:
        conn.execute("ALTER TABLE atos ADD COLUMN orgao TEXT")

    indices = {row[1] for row in conn.execute("PRAGMA index_list(atos)")}
    if "idx_atos_unico" in indices:
        definicao = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_atos_unico'"
        ).fetchone()
        if definicao and "cargo" in (definicao[0] or ""):
            conn.execute("DROP INDEX idx_atos_unico")
            indices.discard("idx_atos_unico")

    if "idx_atos_unico" not in indices:
        # Mantém a extração mais recente e remove duplicatas antigas.
        conn.execute("""
            DELETE FROM atos
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM atos
                GROUP BY IFNULL(edicao, ''), decreto, nome
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX idx_atos_unico ON atos (
                IFNULL(edicao, ''), decreto, nome
            )
        """)

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
            INSERT OR REPLACE INTO atos
                (decreto, tipo, nome, cargo, orgao, data, edicao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (a.decreto, a.tipo, a.nome, a.cargo, a.orgao, a.data, edicao),
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
    query = "SELECT decreto, tipo, nome, cargo, orgao, data, edicao FROM atos WHERE 1=1"
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
            " OR IFNULL(decreto, '') LIKE ? ESCAPE '!')"
        )
        params.extend([padrao, padrao, padrao, padrao])
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
            "edicao": r[6],
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
        )
        for r in reversed(registros)
    ]
