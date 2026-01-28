##########################################################################################
#
# Script name: concat.py
#
# Copyright (c) 2024 4TLAS
# Licensed under the Apache License, Version 2.0. See LICENSE file in the project root for details.
#
# Author: John Macdonald
#
#########################################################################################
import os
import sys
import argparse
import logging
import platform
from datetime import date, datetime
import fnmatch
import pandas as pd
from pathlib import Path
import traceback
import re
from xlsxwriter.utility import xl_col_to_name


# ****************************************************************************************
# Global data and configuration
# ****************************************************************************************
TODAY = date.today()

#---------------------------------------------------------------
# Setup the basic logging stuff and specifics for the log file
# The stdout stream log is configured by command line, so
# the streamhandler is added in 'main'
#---------------------------------------------------------------

# Logging config
logging.captureWarnings(True)
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

# Setup log based on output file/dir
# Log debug messages & higher to file
LOGFILENAME = os.path.basename(sys.argv[0]) + '.log'

fh = logging.FileHandler(LOGFILENAME, mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s]  %(levelname)-8s %(message)s')
fh.setFormatter(formatter)

# Add handlers to log
log.addHandler(fh)

# ****************************************************************************************
# Exceptions
# ****************************************************************************************
class Error(Exception):
    """Base class for exceptions in this module."""
    pass

class GenericException(Error):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return(repr(self.message))
# ****************************************************************************************
# Functions
# ****************************************************************************************
def get_csv_files(indir, root):
    '''
    Returns a list of path/filename of all csv files found.
    - If `indir` is a directory path, search recursively beneath it.
    - Otherwise treat `indir` as a directory-name pattern (legacy behavior).
    '''
    log.info(f'Finding CSVs under {root} using pattern/path "{indir}"')

    search_roots = []
    path_candidate = Path(indir)
    if path_candidate.exists() and path_candidate.is_dir():
        search_roots.append(path_candidate)
    else:
        for r, dirnames, _ in os.walk(root):
            for dirname in dirnames:
                if fnmatch.fnmatch(dirname, indir):
                    search_roots.append(Path(r) / dirname)

    csv_files = []
    for directory in search_roots:
        for r, _, filenames in os.walk(directory):
            for filename in filenames:
                if fnmatch.fnmatch(filename, '*.csv'):
                    csv_files.append(str(Path(r) / filename))

    log.info(f'Found {len(csv_files)} csv files')
    return csv_files

def extract_platform_testcycle(pathname):
    '''
    Extracts the relevant platform and testcycle name from the dir path
    '''
    # Extract the directory names starting with "cs*-" from the pathnames
    #pattern = r"/(cs[a-zA-Z0-9]+-)[^/]*"
    match = re.search(r"(cs[a-zA-Z0-9]+-)[^/]*", pathname)
    if match:
        name = match.group()
        log.debug(f'Name found: {name}')
        
    return name

def concat_files(files):
    '''
    Read all CSVs and return a list of dicts with sheet_name and dataframe.
    '''
    log.info(f'Processing {len(files)} files')
    log.debug(f'Processing files: {files}')

    sheets = []
    for file in files:
        log.info(f'Working on file: {file}')
        df = pd.read_csv(file)
        sheet_name = Path(file).stem[:31]  # Excel sheet name limit
        sheets.append({'sheet': sheet_name, 'df': df})
    return sheets


def csvs_to_excel(sheets, args, add_summary: bool = True):
    '''
    Writes each CSV to its own sheet. If add_summary is True, also writes a combined Summary sheet.
    '''
    log.info(f'Writing Excel with {len(sheets)} sheets')
    excel_file = str(Path(args.outfile).with_suffix('.xlsx'))
    writer = pd.ExcelWriter(excel_file, engine='xlsxwriter')
    red_format = writer.book.add_format({'font_color': 'white', 'bg_color': 'red'})

    sheet_columns: dict[str, list[str]] = {}

    summary_df = None
    if add_summary:
        combined = []
        for item in sheets:
            df = item['df'].copy()
            sheet = item['sheet']
            suite_type = 'unit' if 'unit' in sheet.lower() else 'system' if 'system' in sheet.lower() else ''
            if 'status' in df.columns:
                insert_at = list(df.columns).index('status')
                df.insert(insert_at, 'suite_type', suite_type)
            else:
                df['suite_type'] = suite_type
            df['source_sheet'] = sheet
            combined.append(df)
            sheet_columns[sheet] = list(item['df'].columns)  # per-sheet keeps original columns
        if combined:
            summary_df = pd.concat(combined, ignore_index=True)
            cols = list(summary_df.columns)
            if 'suite_type' in cols and 'status' in cols:
                cols.remove('suite_type')
                cols.insert(cols.index('status'), 'suite_type')
                summary_df = summary_df[cols]
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            sheet_columns['Summary'] = list(summary_df.columns)

    for item in sheets:
        df = item['df']
        sheet = item['sheet']
        df.to_excel(writer, sheet_name=sheet, index=False)
        sheet_columns.setdefault(sheet, list(df.columns))

    # Apply conditional formatting to any "result" column (per sheet)
    for name, ws in writer.sheets.items():
        cols = sheet_columns.get(name, [])
        if ws.dim_rowmax is None or ws.dim_colmax is None:
            continue
        nrows = ws.dim_rowmax + 1
        for idx, header in enumerate(cols):
            if 'result' in str(header).lower():
                col_letter = xl_col_to_name(idx)
                ws.conditional_format(f"{col_letter}2:{col_letter}{nrows}",
                    {'type': 'text', 'criteria': 'containing', 'value': 'fail', 'format': red_format})

    writer.close()
    log.info(f'All done. Excel file {excel_file} is ready.')
    return



                        
# ****************************************************************************************
# arguments
# ****************************************************************************************
def handle_args():
    '''
    Handle the input args and pass back the args object.
    '''
    global log

    # Setup the argument parser and parse the args
    parser = argparse.ArgumentParser(
        description='''
        This script extracts and concatenates results csvs. 
        ''', formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '-v',
        '--verbose',
        default=False,
        dest='verb',
        action='store_true',
        help='Enable verbose output to stdout.  Enables DEBUG statements.')
    parser.add_argument(
        '-q',
        '--quiet',
        default=False,
        action='store_true',
        help='Minimal stdout.')
    parser.add_argument(
        '-o',
        '--outfile',
        default='results_summary',
        help='Output Excel base name [default: results_summary].')
    parser.add_argument(
        '-r',
        '--root',
        default='.',
        help='Start search at this root [default: .]')
    parser.add_argument(
        "dirpat",
        help='Directory path (or pattern) to search for CSVs')
    parser.add_argument(
        '--no-summary',
        action='store_true',
        help='Do not generate a Summary sheet (per-file sheets only)')
    args = parser.parse_args()

    # Log info messages & higher to console based on arguments
    ch = logging.StreamHandler()
    if args.verb:
        ch.setLevel(logging.DEBUG)
    elif args.quiet:
        ch.setLevel(logging.ERROR)
    else:
        ch.setLevel(logging.INFO)

    # Formatter
    formatter = logging.Formatter(
        '[%(funcName)25s:%(lineno)-5s]  %(levelname)-8s %(message)s')
    ch.setFormatter(formatter)

    # Add handlers to log
    log.addHandler(ch)

    # output some interesting stuff for the user
    log.info( '++++++++++++++++++++++++++++++++++++++++++++++')
    log.info( f'+  {os.path.basename(sys.argv[0])}')
    log.info( f'+  Python Version: {platform.python_version()}')
    log.info( f'+  Today is: {TODAY}')
    log.info( f'+  Root dir: {args.root}')
    log.info( f'+  Output File: {args.outfile}.xlsx')
    log.info( '++++++++++++++++++++++++++++++++++++++++++++++')

    return args



# ****************************************************************************************
# Main
# ****************************************************************************************
def main():

    global log

    # handle the args
    args = handle_args()

    try:
        # Find all the csv files
        files = get_csv_files(args.dirpat, args.root)

        # Read them into dataframes
        sheets = concat_files(files)

        # make an excel file
        csvs_to_excel(sheets, args, add_summary=not getattr(args, 'no_summary', False))
        
    except Exception as e:
        log.error('XXX Exception info: {}'.format(traceback.format_exc()))
        log.error('XXX FAIL with: {}'.format(e))
        return 1


    log.info('All done')
    return 0
# ------------------------------------------------------------------------------

if __name__ == '__main__':
    main()
