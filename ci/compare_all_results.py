##########################################################################################
#
# Script name: concat_all_results.py
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
import pandas as pd
import traceback
import glob
import re
import openpyxl
from pathlib import Path
from xlsxwriter.utility import xl_col_to_name

# Logging config
logging.captureWarnings(True)
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

# Setup log based on output file/dir
LOGFILENAME = os.path.basename(sys.argv[0]) + '.log'

fh = logging.FileHandler(LOGFILENAME, mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s]  %(levelname)-8s %(message)s')
fh.setFormatter(formatter)

# Add handlers to log
log.addHandler(fh)

# ****************************************************************************************
# Functions
# ****************************************************************************************

def find_files(pattern, root, max_files=None):
    '''
    Returns a list of path/filename of all Excel files matching pattern found, limited to max_files (newest first) if provided.
    '''
    log.info(f'Finding Excel files at {root} matching {pattern}')
    search_pattern = os.path.join(root, '**', pattern)
    matches = glob.glob(search_pattern, recursive=True)
    if not matches and '*'+pattern not in pattern:
        alt_pattern = os.path.join(root, '**', f'*{pattern}*')
        log.info(f'No matches; retrying with relaxed pattern {alt_pattern}')
        matches = glob.glob(alt_pattern, recursive=True)
    # Deduplicate
    matches = sorted(set(matches), key=lambda p: os.path.getmtime(p), reverse=True)
    if max_files:
        matches = matches[:max_files]
    log.info(f'Found {len(matches)} Excel files')
    return matches


def custom_merge_old(df1, df2):
    '''
    Merges rows with same name/platform pair. The algorithm is AND gate.
    '''
    # Merge two dataframes df1 and df2
    merged = pd.concat([df1, df2], ignore_index=True)
    merged.fillna("", inplace=True)

    # Dynamically find the column with "Result" in its name
    result_column = [col for col in merged.columns if 'Result' in col][0]

    # Applying the rules for 'result' merging
    merged.sort_values(['name', 'platform', result_column], ascending=[True, True, False], inplace=True)
    merged.drop_duplicates(subset=['name', 'platform'], keep='first', inplace=True)

    return merged

def custom_merge(df1, df2, keys: list[str]):
    '''
    Merges rows with same key columns; outer join.
    '''
    common_keys = [k for k in keys if k in df1.columns and k in df2.columns]
    if not common_keys:
        merged = pd.concat([df1, df2], ignore_index=True)
    else:
        # Avoid duplicate non-key columns by suffixing, then drop the dupes
        merged = pd.merge(df1, df2, on=common_keys, how='outer', suffixes=('_left', '_right'))
        # Drop duplicated columns from the right side if they conflict (keep left)
        for col in list(merged.columns):
            if col.endswith('_right'):
                base = col[:-6]
                if f"{base}_left" in merged.columns:
                    merged.drop(columns=[col], inplace=True)
                else:
                    merged.rename(columns={col: base}, inplace=True)
        # Remove _left suffixes
        merged.rename(columns={c: c[:-5] for c in merged.columns if c.endswith('_left')}, inplace=True)
    merged.fillna("", inplace=True)
    return merged


def compare_excel_files(files, args):
    '''
    Create the comparison file
    '''
    log.info(f'Processing {len(files)} files')
    log.debug(f'Processing files: {files}')

    out_path = Path(args.outfile)
    if not out_path.suffix:
        out_path = out_path.with_name(f"{out_path.name}-summary-comparison.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    excel_file = str(out_path)

    key_cols = [k.strip() for k in args.key_cols.split(',') if k.strip()]
    keep_cols = []
    if hasattr(args, 'keep_cols') and args.keep_cols:
        keep_cols = [k.strip() for k in args.keep_cols.split(',') if k.strip()]

    def _sanitize_sheet(name: str) -> str:
        return re.sub(r'[^A-Za-z0-9_]', '_', str(name))[:31]

    def _extract_run_id(file_path: str) -> str:
        """Best-effort: prefer prefixed run number like '78-1990..._file' then any numeric part."""
        p = Path(file_path)
        name = p.name
        m = re.match(r'^(\d+)-(\d+)', name)
        if not m and p.parent:
            m = re.match(r'^(\d+)-(\d+)', p.parent.name)
        if m:
            return m.group(1)  # run number
        parts = p.parts
        for part in reversed(parts):
            if part.isdigit():
                return part
            m = re.search(r'(\d+)', part)
            if m:
                return m.group(1)
        return p.stem

    def _prune_cols(df: pd.DataFrame, *, keep_cols_opt: list[str] | None = None) -> pd.DataFrame:
        # Ensure all key columns exist
        for k in key_cols:
            if k not in df.columns:
                df[k] = ''
        if keep_cols_opt:
            cols = [c for c in keep_cols_opt if c in df.columns]
            if cols:
                df = df[cols].copy()
        return df

    def _merge_entries(entries: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
        merged = None
        for run_label, df in entries:
            value_cols = [c for c in df.columns if c not in key_cols]
            if len(value_cols) == 1:
                renames = {value_cols[0]: run_label}
            else:
                renames = {c: f"{run_label}:{c}" for c in value_cols}
            df_renamed = df.rename(columns=renames)
            merged = df_renamed if merged is None else merged.merge(df_renamed, on=key_cols, how='outer')
        if merged is None:
            merged = pd.DataFrame(columns=key_cols)
        # Order columns with keys first, then data columns newest->oldest (rightmost entries in merge were older)
        key_prefix = [c for c in key_cols if c in merged.columns]
        data_cols = [c for c in merged.columns if c not in key_cols]
        numeric_cols = [c for c in data_cols if str(c).isdigit()]
        non_numeric_cols = [c for c in data_cols if not str(c).isdigit()]
        numeric_cols = sorted(numeric_cols, key=lambda x: int(x), reverse=True)
        non_numeric_cols = sorted(non_numeric_cols, reverse=True)
        ordered_cols = key_prefix + numeric_cols + non_numeric_cols
        merged = merged[ordered_cols]
        if ordered_cols:
            merged.fillna("", inplace=True)
        # Stable sort by key columns if present
        if key_cols:
            present_keys = [k for k in key_cols if k in merged.columns]
            if present_keys:
                merged.sort_values(present_keys, inplace=True)
        return merged

    # Collect data
    grouped: dict[str, list[tuple[str, pd.DataFrame]]] = {}
    run_id_seen: dict[str, int] = {}
    is_coverage_mode = key_cols == ['file']

    for file in files:
        log.debug(f"Working on file: {file}")
        try:
            xls = pd.ExcelFile(file, engine='openpyxl')
        except Exception as e:
            log.warning(f"Skipping file {file}: {e}")
            continue

        run_id_raw = _extract_run_id(file)

        idx = run_id_seen.get(run_id_raw, 0)
        run_id_seen[run_id_raw] = idx + 1
        run_label = run_id_raw if idx == 0 else f"{run_id_raw}_{idx}"
        run_label = _sanitize_sheet(run_label)

        for sheet_name in xls.sheet_names:
            raw_sheet_key = sheet_name.lower().strip()
            sheet_key = raw_sheet_key
            if is_coverage_mode:
                if 'combine' in raw_sheet_key:
                    sheet_key = 'coverage_combined'
                elif 'unit' in raw_sheet_key:
                    sheet_key = 'coverage_unit'
                elif 'system' in raw_sheet_key:
                    sheet_key = 'coverage_system'
            # Tests: only use the Summary sheet; we'll derive system/unit from it.
            if not is_coverage_mode and sheet_key != 'summary':
                continue
            df = xls.parse(sheet_name)
            # For system/unit sheets that lack suite_type, add it (defensive)
            if not is_coverage_mode and 'suite_type' not in df.columns:
                if 'system' in sheet_key:
                    df['suite_type'] = 'system'
                elif 'unit' in sheet_key:
                    df['suite_type'] = 'unit'
                else:
                    df['suite_type'] = ''
            df = _prune_cols(df, keep_cols_opt=keep_cols if not is_coverage_mode else None)
            grouped.setdefault(sheet_key, []).append((run_label, df))
        log.info(f"Processed file: {file}")

    with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
        workbook  = writer.book

        if not grouped:
            log.warning('No input files provided; writing Info sheet placeholder.')
            pd.DataFrame([{'info': 'No input files found for comparison.'}]).to_excel(writer, sheet_name='Info', index=False)
            log.info(f'Wrote placeholder comparison file => {excel_file}')
            return out_path

        red_format = workbook.add_format({'bg_color': '#FF0000', 'font_color': 'white'})
        written_sheets: list[tuple[str, pd.DataFrame]] = []

        if is_coverage_mode:
            cov_cols_priority = ('coverage_pct', 'coverage', 'cover')
            for sheet_key, sheet_name in (
                ('coverage_combined', 'Combined'),
                ('coverage_unit', 'Unit'),
                ('coverage_system', 'System'),
            ):
                entries = grouped.get(sheet_key, [])
                log.info(f'Coverage sheet "{sheet_name}": {len(entries)} run(s) found')
                merged_all = None
                for run_label, df in entries:
                    if merged_all is not None and run_label in merged_all.columns:
                        continue
                    cov_col = None
                    for cand in cov_cols_priority:
                        if cand in df.columns:
                            cov_col = cand
                            break
                    if cov_col is None and 'statements' in df.columns and 'missing' in df.columns:
                        df['coverage_pct'] = (df['statements'] - df['missing']) / df['statements'] * 100
                        cov_col = 'coverage_pct'
                    if cov_col is None:
                        # Best effort: pick the last column if it is numeric-ish
                        for col in reversed(df.columns.tolist()):
                            if col != 'file':
                                cov_col = col
                                break
                    if cov_col is None or cov_col == 'file':
                        continue
                    df_renamed = df[['file', cov_col]].rename(columns={cov_col: run_label})
                    merged_all = df_renamed if merged_all is None else merged_all.merge(df_renamed, on=['file'], how='outer')
                if (merged_all is None or merged_all.empty) and (not entries) and grouped:
                    for alt_key, alt_entries in grouped.items():
                        for run_label, df in alt_entries:
                            if merged_all is not None and run_label in merged_all.columns:
                                continue
                            cov_col = None
                            for cand in cov_cols_priority:
                                if cand in df.columns:
                                    cov_col = cand
                                    break
                            if cov_col is None and 'statements' in df.columns and 'missing' in df.columns:
                                df['coverage_pct'] = (df['statements'] - df['missing']) / df['statements'] * 100
                                cov_col = 'coverage_pct'
                            if cov_col is None:
                                for col in reversed(df.columns.tolist()):
                                    if col != 'file':
                                        cov_col = col
                                        break
                            if cov_col is None or cov_col == 'file':
                                continue
                            df_renamed = df[['file', cov_col]].rename(columns={cov_col: run_label})
                            merged_all = df_renamed if merged_all is None else merged_all.merge(df_renamed, on=['file'], how='outer')
                if merged_all is None:
                    merged_all = pd.DataFrame(columns=['file'])
                # Reorder columns: file first, then run labels sorted newest/desc (numeric when possible)
                data_cols = [c for c in merged_all.columns if c != 'file']
                numeric_cols = [c for c in data_cols if str(c).isdigit()]
                non_numeric_cols = [c for c in data_cols if not str(c).isdigit()]
                numeric_cols = sorted(numeric_cols, key=lambda x: int(x), reverse=True)
                non_numeric_cols = sorted(non_numeric_cols, reverse=True)
                ordered = ['file'] + numeric_cols + non_numeric_cols
                merged_all = merged_all[ordered] if ordered else merged_all
                merged_all.fillna("", inplace=True)
                merged_all.to_excel(writer, sheet_name=sheet_name, index=False)
                written_sheets.append((sheet_name, merged_all))
        else:
            # Build merged summary from the Summary sheet, then derive system/unit
            summary_entries = grouped.get('summary', [])
            merged_summary = _merge_entries(summary_entries) if summary_entries else pd.DataFrame(columns=key_cols)
            merged_summary.to_excel(writer, sheet_name='Summary', index=False)
            written_sheets.append(('Summary', merged_summary))

            if 'suite_type' in merged_summary.columns:
                for suite_val, sheet_name in [('system', 'System'), ('unit', 'Unit')]:
                    filtered = merged_summary[merged_summary['suite_type'].str.lower() == suite_val]
                    filtered.to_excel(writer, sheet_name=sheet_name, index=False)
                    written_sheets.append((sheet_name, filtered))

        # Conditional formatting on status columns only
        for sheet_name, df in written_sheets:
            worksheet = writer.sheets[sheet_name]
            rows, cols = df.shape
            for col_idx, col_name in enumerate(df.columns):
                if 'status' not in col_name.lower():
                    continue
                if rows == 0:
                    continue
                start_col = xl_col_to_name(col_idx, col_abs=False)
                cell_range = f"{start_col}2:{start_col}{rows+1}"
                worksheet.conditional_format(cell_range, {
                    'type': 'text',
                    'criteria': 'containing',
                    'value': 'fail',
                    'format': red_format
                })

    log.info(f'All done. Comparison Excel file {excel_file} is ready.')
    return out_path




# ****************************************************************************************
# arguments
# ****************************************************************************************
def handle_args():
    '''
    Handle the input args and pass back the args object.
    '''
    global log

    parser = argparse.ArgumentParser(
        description='''
        This script finds all CSV files matching a given pattern and concatenates them into one file.
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
        '-p',
        '--pattern',
        required=True,
        help='File pattern to search for.')
    parser.add_argument(
        '-r',
        '--root',
        default='.',
        help='Directory to start search. [default: .]')
    parser.add_argument(
        '--max-files',
        type=int,
        default=10,
        help='Max number of matching files to process (newest first). [default: 10]')
    parser.add_argument(
        '--key-cols',
        default='name,platform',
        help='Comma-separated key columns to merge on (fallback to available columns). [default: name,platform]')
    parser.add_argument(
        '-o',
        '--outfile',
        default='results-comparison.csv',
        help='Output file [default: results-comparison.csv]')    
    parser.add_argument(
        '--keep-cols',
        default='',
        help='Comma-separated list of columns to retain (e.g., "file,coverage_pct")')
    parser.add_argument(
        '--prefix',
        default='',
        help='Prefix for the output file [default: ]')
    args = parser.parse_args()

    ch = logging.StreamHandler()
    if args.verb:
        ch.setLevel(logging.DEBUG)
    elif args.quiet:
        ch.setLevel(logging.ERROR)
    else:
        ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '[%(funcName)25s:%(lineno)-5s]  %(levelname)-8s %(message)s')
    ch.setFormatter(formatter)

    log.addHandler(ch)

    log.info( '++++++++++++++++++++++++++++++++++++++++++++++')
    log.info( f'+  {os.path.basename(sys.argv[0])}')
    log.info( f'+ Directory:        {args.root}')
    log.info( f'+ CSV File pattern: {args.pattern}')
    log.info( f'+ Output File:      {args.outfile}')
    log.info( '++++++++++++++++++++++++++++++++++++++++++++++')
    
    return args

# ****************************************************************************************
# Main
# ****************************************************************************************
def main():
    global log

    args = handle_args()

    try:
        files = find_files(args.pattern, args.root, args.max_files)
        compare_excel_files(files, args)
        
    except Exception as e:
        log.error('XXX Exception info: {}'.format(traceback.format_exc()))
        log.error('XXX FAIL with: {}'.format(e))
        return 1

    log.info('All done')
    return 0

# ------------------------------------------------------------------------------
if __name__ == '__main__':
    main()
