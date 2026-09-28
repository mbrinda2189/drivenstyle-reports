"""
app.reports - The 12 monthly reports
====================================

    data.py      Works out every figure for a month from the stored
                 invoices, the masters (rates on the invoice date) and the
                 monthly inputs. No Excel and no screens here.
    workbook.py  Writes those figures into the Excel workbook: a cover
                 sheet, the 12 report sheets and a "Not included" sheet.
                 Totals, profits and percentages are live Excel formulas.
    generate.py  One call used by the Generate and History screens:
                 build the data, write the workbook, record the run.
"""