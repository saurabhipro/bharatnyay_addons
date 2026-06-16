# -*- coding: utf-8 -*-
"""PDF worker settings — odoo.conf, then System Parameters, then defaults."""
import logging
import os

_logger = logging.getLogger(__name__)

CONF_SECTION = 'bharatnyay_pdf'

PARAM_PARALLEL_WORKERS = 'bharat.pdf.parallel_workers'
PARAM_FAST_MODE = 'bharat.pdf.fast_mode'
PARAM_MERGE_CHUNK = 'bharat.pdf.merge_chunk'

CONF_PARALLEL_WORKERS = 'bharat_pdf_parallel_workers'
CONF_FAST_MODE = 'bharat_pdf_fast_mode'
CONF_MERGE_CHUNK = 'bharat_pdf_merge_chunk'


def default_parallel_workers():
    """Use most cores but leave one free for Odoo/UI."""
    cpu = os.cpu_count() or 4
    return min(6, max(2, cpu - 1))


def _odoo_conf_raw(section_key, options_key=None):
    """Read from odoo.conf ([bharatnyay_pdf] section, then [options] flat keys)."""
    try:
        from odoo.tools import config
    except ImportError:
        return None

    val = config.get_misc(CONF_SECTION, section_key, None)
    if val is not None and str(val).strip() != '':
        return val
    if options_key:
        val = config.get(options_key, None)
        if val is not None and str(val).strip() != '':
            return val
    return None


def _as_bool(val, default=False):
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('true', '1', 'yes', 'on')


def read_parallel_workers(icp_get):
    """Worker count: odoo.conf → System Parameter → auto."""
    conf = _odoo_conf_raw('parallel_workers', CONF_PARALLEL_WORKERS)
    raw = conf if conf is not None else icp_get(PARAM_PARALLEL_WORKERS, '0')
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return default_parallel_workers()
    return min(max(1, n), 16)


def read_merge_chunk(icp_get):
    conf = _odoo_conf_raw('merge_chunk', CONF_MERGE_CHUNK)
    raw = conf if conf is not None else icp_get(PARAM_MERGE_CHUNK, '25')
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 25
    return min(max(5, n), 100)


def read_fast_mode(icp_get):
    conf = _odoo_conf_raw('fast_mode', CONF_FAST_MODE)
    if conf is not None:
        return _as_bool(conf, True)
    return _as_bool(icp_get(PARAM_FAST_MODE, 'True'), True)


def pdf_settings_summary(icp_get):
    """Debug/help payload for logs or support."""
    return {
        'parallel_workers': read_parallel_workers(icp_get),
        'merge_chunk': read_merge_chunk(icp_get),
        'fast_mode': read_fast_mode(icp_get),
        'source_workers': (
            'odoo.conf' if _odoo_conf_raw('parallel_workers', CONF_PARALLEL_WORKERS) is not None
            else 'system_parameter'
        ),
    }
