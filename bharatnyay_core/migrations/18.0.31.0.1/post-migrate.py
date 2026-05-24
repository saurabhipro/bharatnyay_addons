# -*- coding: utf-8 -*-

def migrate(cr, version):
    cr.execute("""
        UPDATE bharat_loan
        SET loan_number = TRIM(loan_number)
        WHERE loan_number IS NOT NULL
          AND loan_number != TRIM(loan_number)
    """)
    cr.execute("""
        SELECT TRIM(loan_number), array_agg(id ORDER BY id)
        FROM bharat_loan
        WHERE loan_number IS NOT NULL AND TRIM(loan_number) != ''
        GROUP BY TRIM(loan_number)
        HAVING COUNT(*) > 1
    """)
    for loan_number, ids in cr.fetchall():
        for dup_id in ids[1:]:
            cr.execute(
                "UPDATE bharat_loan SET loan_number = %s WHERE id = %s",
                ('%s-dup-%s' % (loan_number, dup_id), dup_id),
            )
