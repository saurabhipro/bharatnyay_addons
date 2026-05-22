# -*- coding: utf-8 -*-
"""Idempotent PostgreSQL fixes for partially upgraded ``bharat.loan`` tables."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

FK_SPECS = (
    ('region_id', 'bharat_region', 'bharat.region', 'region'),
    ('borrower_state_id', 'bharat_borrower_state', 'bharat.borrower_state', 'borrower_state'),
    ('branch_id', 'bharat_branch', 'bharat.branch', 'branch'),
    ('location_id', 'bharat_loan_location', 'bharat.loan_location', 'location'),
    ('product_class_id', 'bharat_product_class', 'bharat.product_class', 'product_classification'),
    ('writeoff_id', 'bharat_writeoff', 'bharat.writeoff', 'write_off'),
    ('law_firm_id', 'bharat_law_firm', 'bharat.law_firm', 'law_firm_name'),
)


def _fqn_table(cr, relname):
    """Return qualified ``schemaname.tablename`` using quoted identifiers."""
    cr.execute("""
        SELECT tc.table_schema, tc.table_name
          FROM information_schema.tables tc
         WHERE tc.table_catalog = current_database()
           AND tc.table_schema IN (SELECT UNNEST(current_schemas(true)))
           AND tc.table_name = %s
        ORDER BY CASE WHEN tc.table_schema = 'public' THEN 0 ELSE 1 END
        LIMIT 1
    """, (relname,))
    row = cr.fetchone()
    if not row:
        return None
    sch, tbl = row
    cr.execute(
        """SELECT concat(quote_ident(%s::text), '.', quote_ident(%s::text))""",
        (sch, tbl),
    )
    return cr.fetchone()[0]


def _column_exists(cr, schema, bare_table, column):
    cr.execute("""
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.columns c
             WHERE c.table_catalog = current_database()
               AND c.table_schema = %s
               AND c.table_name = %s
               AND c.column_name = %s)
    """, (schema, bare_table, column))
    return cr.fetchone()[0]


def repair_loan_foreign_key_columns(cr):
    """Add missing ``*_id`` columns on ``bharat_loan``, back-fill from legacy text columns."""
    cr.execute("""
        SELECT tc.table_schema, tc.table_name
          FROM information_schema.tables tc
         WHERE tc.table_catalog = current_database()
           AND tc.table_schema IN (SELECT UNNEST(current_schemas(true)))
           AND tc.table_name = 'bharat_loan'
        ORDER BY CASE WHEN tc.table_schema = 'public' THEN 0 ELSE 1 END
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        return

    loan_schema, loan_bare_name = row
    loan_fqn = _fqn_table(cr, 'bharat_loan')
    if not loan_fqn:
        return

    for fk_col, ref_bare_rel, _comodel_name, _legacy_col in FK_SPECS:
        if _column_exists(cr, loan_schema, loan_bare_name, fk_col):
            continue

        ref_fqn = _fqn_table(cr, ref_bare_rel)

        # Always create the missing column first, so UI/search_read won't crash.
        cr.execute("ALTER TABLE ONLY {} ADD COLUMN {} INTEGER".format(loan_fqn, fk_col))
        _logger.warning(
            'bharatnyay_core: repaired missing column %s on %s',
            fk_col,
            loan_fqn,
        )

        # Try adding FK only when the reference table exists.
        if ref_fqn:
            try:
                cr.execute(
                    """
                    ALTER TABLE ONLY {loan}
                      ADD CONSTRAINT {cons}
                      FOREIGN KEY ({fk}) REFERENCES {ref}(id) ON DELETE SET NULL
                    """.format(
                        loan=loan_fqn,
                        cons='bharat_loan_{}_fkey'.format(fk_col),
                        fk=fk_col,
                        ref=ref_fqn,
                    )
                )
            except Exception:
                _logger.warning(
                    'bharatnyay_core: FK creation skipped for %s -> %s',
                    fk_col,
                    ref_bare_rel,
                )

    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()

    for fk_col, ref_bare_rel, comodel_name, legacy_col in FK_SPECS:
        if (
            not _column_exists(cr, loan_schema, loan_bare_name, fk_col)
            or not _column_exists(cr, loan_schema, loan_bare_name, legacy_col)
        ):
            continue

        Meta = env[comodel_name]
        cr.execute("""
                SELECT DISTINCT trim({legacy}::text)
                  FROM {loan}
                 WHERE {fk} IS NULL
                   AND trim(coalesce({legacy}::text, '')) <> ''
        """.format(loan=loan_fqn, fk=fk_col, legacy=legacy_col))

        distinct_names = [r[0] for r in cr.fetchall() if r[0]]
        cache_by_lower = {}

        def _tid_for(nm):
            k = nm.strip().lower()
            if k in cache_by_lower:
                return cache_by_lower[k]
            meta = Meta.search([('name', '=ilike', nm.strip())], limit=1)
            if meta:
                cache_by_lower[k] = meta.id
                return meta.id
            meta = Meta.create({'name': nm.strip()})
            cache_by_lower[k] = meta.id
            return meta.id

        for nm in distinct_names:
            tid = _tid_for(nm)
            sql = '''UPDATE {} SET {} = %s WHERE {} IS NULL AND trim(coalesce({}::text, '')) = %s'''
            cr.execute(sql.format(loan_fqn, fk_col, fk_col, legacy_col), (tid, nm))

        _logger.info(
            'bharatnyay_core: back-filled masters for %s from %s',
            fk_col,
            legacy_col,
        )


def repair_loan_arbitrator_id_column(cr):
    """Add ``arbitrator_id`` on ``bharat_loan`` if the ORM field exists but SQL is behind (partial upgrades)."""
    cr.execute("""
        SELECT tc.table_schema, tc.table_name
          FROM information_schema.tables tc
         WHERE tc.table_catalog = current_database()
           AND tc.table_schema IN (SELECT UNNEST(current_schemas(true)))
           AND tc.table_name = 'bharat_loan'
        ORDER BY CASE WHEN tc.table_schema = 'public' THEN 0 ELSE 1 END
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        return
    loan_schema, loan_bare_name = row
    loan_fqn = _fqn_table(cr, 'bharat_loan')
    if not loan_fqn:
        return
    if _column_exists(cr, loan_schema, loan_bare_name, 'arbitrator_id'):
        return

    cr.execute("ALTER TABLE ONLY {} ADD COLUMN arbitrator_id INTEGER".format(loan_fqn))
    _logger.warning('bharatnyay_core: repaired missing column arbitrator_id on %s', loan_fqn)

    ref_fqn = _fqn_table(cr, 'res_users')
    if ref_fqn:
        try:
            cr.execute(
                """
                ALTER TABLE ONLY {loan}
                  ADD CONSTRAINT bharat_loan_arbitrator_id_fkey
                  FOREIGN KEY (arbitrator_id) REFERENCES {ref}(id) ON DELETE SET NULL
                """.format(loan=loan_fqn, ref=ref_fqn)
            )
        except Exception:
            _logger.warning('bharatnyay_core: FK creation skipped for arbitrator_id -> res_users')


def repair_loan_hearing_columns(cr):
    """Add hearing / interim columns on ``bharat_loan`` when Python model is ahead of SQL (skipped ``-u``)."""
    cr.execute("""
        SELECT tc.table_schema, tc.table_name
          FROM information_schema.tables tc
         WHERE tc.table_catalog = current_database()
           AND tc.table_schema IN (SELECT UNNEST(current_schemas(true)))
           AND tc.table_name = 'bharat_loan'
        ORDER BY CASE WHEN tc.table_schema = 'public' THEN 0 ELSE 1 END
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        return
    loan_schema, loan_bare_name = row
    loan_fqn = _fqn_table(cr, 'bharat_loan')
    if not loan_fqn:
        return

    amount_sql_type = 'double precision'
    cr.execute("""
        SELECT data_type, numeric_precision, numeric_scale
          FROM information_schema.columns c
         WHERE c.table_catalog = current_database()
           AND c.table_schema = %s
           AND c.table_name = %s
           AND c.column_name = 'claim_amount'
    """, (loan_schema, loan_bare_name))
    claim_row = cr.fetchone()
    if claim_row and claim_row[0] == 'numeric':
        prec, scale = claim_row[1] or 24, claim_row[2]
        scale = scale if scale is not None else 2
        amount_sql_type = 'NUMERIC({}, {})'.format(prec, scale)
    elif claim_row and claim_row[0] == 'double precision':
        amount_sql_type = 'double precision'

    ddl_list = (
        ('hearing_datetime', 'timestamp without time zone'),
        ('hearing_video_url', 'character varying'),
        ('hearing_notes', 'text'),
        ('hearing_link_type', 'character varying'),
        ('interim_award_date', 'timestamp without time zone'),
        ('interim_award_notes', 'text'),
        ('interim_award_amount', amount_sql_type),
    )
    changed = False
    for col, ddl in ddl_list:
        if _column_exists(cr, loan_schema, loan_bare_name, col):
            continue
        cr.execute('ALTER TABLE ONLY {} ADD COLUMN {} {}'.format(loan_fqn, col, ddl))
        changed = True
        _logger.warning('bharatnyay_core: repaired missing column %s on %s', col, loan_fqn)
    if changed:
        api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()


DEMO_USERS_ROLES = (
    ('bn.demo.arb.alpha', 'Demo Arbitrator Alpha', 'arb.alpha.demo@bharatnyay.example.com', 'arbitrator'),
    ('bn.demo.arb.beta', 'Demo Arbitrator Beta', 'arb.beta.demo@bharatnyay.example.com', 'arbitrator'),
    ('bn.demo.case.manager', 'Demo Case Manager', 'manager.demo@bharatnyay.example.com', 'case_manager'),
    ('bn.demo.lender', 'Demo Lender', 'lender.demo@bharatnyay.example.com', 'lender'),
    ('bn.demo.borrower', 'Demo Borrower', 'borrower.demo@bharatnyay.example.com', 'borrower'),
)


def _table_exists(cr, table_name):
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.tables
             WHERE table_catalog = current_database()
               AND table_name = %s
        )
        """,
        (table_name,),
    )
    return bool(cr.fetchone()[0])


def migrate_user_role_assignments_to_res_users(cr):
    """Copy legacy assignment rows onto ``res.users``, then drop the old table."""
    if not _table_exists(cr, 'bharat_user_role_assignment'):
        return
    if not _column_exists(cr, 'public', 'res_users', 'bharat_role'):
        _logger.warning('bharatnyay_core: skip role migration — res_users.bharat_role missing')
        return

    cr.execute("""
        SELECT DISTINCT ON (user_id)
               user_id, role, region_id, borrower_state_id, branch_id, location_id, note
          FROM bharat_user_role_assignment
         WHERE active IS TRUE AND user_id IS NOT NULL
         ORDER BY user_id, id DESC
    """)
    rows = cr.fetchall()
    for user_id, role, region_id, state_id, branch_id, location_id, note in rows:
        cr.execute("""
            UPDATE res_users
               SET bharat_role = %s,
                   bharat_region_id = %s,
                   bharat_borrower_state_id = %s,
                   bharat_branch_id = %s,
                   bharat_location_id = %s,
                   bharat_role_note = COALESCE(%s, bharat_role_note)
             WHERE id = %s
               AND (bharat_role IS NULL OR bharat_role = '')
        """, (role, region_id, state_id, branch_id, location_id, note, user_id))

    cr.execute('DROP TABLE IF EXISTS bharat_user_role_assignment CASCADE')
    _logger.info('bharatnyay_core: migrated %s user role assignment(s) to res.users', len(rows))


def seed_bharatnyay_demo_users_and_roles(cr):
    """Idempotent demo users with BharatNyay operational roles (sandbox passwords)."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    Users = env['res.users'].sudo()

    group_user = env.ref('base.group_user', raise_if_not_found=False)
    if not group_user:
        _logger.warning('bharatnyay_core: skip demo seed — base.group_user missing')
        return

    company = env.ref('base.main_company', raise_if_not_found=False)
    cid = company.id if company else False

    pwd = 'BnDemo#2026'

    def _ensure_user(login, name, email):
        u = Users.search([('login', '=', login)], limit=1)
        if u:
            return u
        vals = {
            'name': name,
            'login': login,
            'email': email,
            'groups_id': [(6, 0, [group_user.id])],
        }
        if cid:
            vals['company_id'] = cid
            vals['company_ids'] = [(6, 0, [cid])]
        u = Users.create(vals)
        u.password = pwd
        _logger.info('bharatnyay_core: created demo user %s', login)
        return u

    def _ensure_role(user, role):
        if user.bharat_role:
            return
        try:
            user.write({'bharat_role': role})
            _logger.info('bharatnyay_core: set role %s on user %s', role, user.login)
        except Exception:
            _logger.warning('bharatnyay_core: could not set role %s on user %s', role, user.login)

    for login, name, email, role in DEMO_USERS_ROLES:
        usr = _ensure_user(login, name, email)
        _ensure_role(usr, role)

    env.invalidate_all()


def post_init_hook(cr, registry):
    """After install/upgrade: draft demo invoice for batch BN-DEMO-BILL when sample data exists."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.move'].sudo()._bharat_demo_seed_batch_invoice()


__all__ = [
    'repair_loan_foreign_key_columns',
    'repair_loan_arbitrator_id_column',
    'repair_loan_hearing_columns',
    'migrate_user_role_assignments_to_res_users',
    'seed_bharatnyay_demo_users_and_roles',
]
