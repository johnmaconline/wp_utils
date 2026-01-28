##########################################################################################
#
# Script name: results_processing.py
# Description: Post-process test/coverage artifacts (JUnit -> CSV, coverage index HTML).
#
##########################################################################################

import argparse
import csv
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Tuple


def _map_class_to_source(classname: str) -> str:
    '''
    Heuristic mapping from test classname to source file under test.
    '''
    if not classname:
        return ''
    low = classname.lower()
    if 'job_description_getter' in low:
        return 'tools/job_description_getter.py'
    if 'jobber_agent' in low:
        return 'jobber_agent.py'
    if 'results_processing' in low:
        return 'tools/results_processing.py'
    if 'document_tools' in low or 'resume_converter' in low:
        return 'tools/document_tools.py'
    if 'resume_normalizer' in low:
        return 'tools/resume_normalizer.py'
    first = classname.split('.')[0]
    return f'{first}.py' if first else ''


def parse_junit_to_rows(junit_path: Path) -> list[tuple[str, str, str, str, str, str]]:
    '''
    Read a JUnit XML file and return rows of (classname, source_file, testcase, status, time, test_file).
    '''
    rows: list[tuple[str, str, str, str, str, str]] = []
    tree = ET.parse(junit_path)
    root = tree.getroot()
    for tc in root.iter('testcase'):
        name = tc.get('name') or ''
        classname = tc.get('classname') or ''
        test_file = f"{classname.replace('.', '/')}.py" if classname else ''
        source_file = _map_class_to_source(classname)
        time = tc.get('time') or ''
        status = 'passed'
        for child in tc:
            if child.tag in ('failure', 'error'):
                status = 'failed'
            elif child.tag == 'skipped':
                status = 'skipped'
        rows.append((classname, source_file, name, status, time, test_file))
    return rows


def write_csv(rows: list[tuple[str, str, str, str, str, str]], csv_path: Path) -> Path:
    '''
    Write rows to CSV with headers.
    '''
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['classname', 'source_file', 'testcase', 'status', 'time', 'test_file'])
        writer.writerows(rows)
    return csv_path


def parse_coverage_xml(xml_path: Path) -> List[Tuple[str, int, int, float]]:
    '''
    Read coverage.py XML report and return rows of (filename, statements, missing, coverage_pct).
    '''
    tree = ET.parse(xml_path)
    root = tree.getroot()
    rows: List[Tuple[str, int, int, float]] = []
    for cls in root.findall('.//class'):
        filename = cls.get('filename') or ''
        lines = cls.findall('.//line')
        statements = len(lines)
        missing = sum(1 for ln in lines if int(ln.get('hits', '0')) == 0)
        cov = 0.0 if statements == 0 else round((statements - missing) / statements * 100, 2)
        rows.append((filename, statements, missing, cov))
    return rows


def write_coverage_csv(rows: List[Tuple[str, int, int, float]], csv_path: Path) -> Path:
    '''
    Write coverage rows to CSV with headers.
    '''
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['file', 'statements', 'missing', 'coverage_pct'])
        writer.writerows(rows)
    return csv_path


def generate_coverage_index(root: Path, unit_dir: Path, system_dir: Path, combined_dir: Path) -> Path:
    '''
    Write a tabbed coverage summary index linking unit/system/combined coverage reports.
    '''
    root.mkdir(parents=True, exist_ok=True)

    def rel_to(dir_path: Path) -> str:
        clean = dir_path.as_posix().lstrip('./').rstrip('/')
        return f"../{clean}/index.html"

    unit_rel = rel_to(unit_dir)
    system_rel = rel_to(system_dir)
    combined_rel = rel_to(combined_dir)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Coverage Reports</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    .tabs {{ display: flex; gap: 12px; margin-bottom: 16px; }}
    .tab {{ padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; background: #f3f3f3; cursor: pointer; }}
    .tab.active {{ background: #dbeafe; border-color: #93c5fd; }}
    iframe {{ width: 100%; height: 80vh; border: 1px solid #ccc; }}
  </style>
</head>
<body>
  <div class="tabs">
    <div class="tab active" onclick="show('unit')">Unit</div>
    <div class="tab" onclick="show('system')">System</div>
    <div class="tab" onclick="show('combined')">Combined</div>
  </div>
  <iframe id="frame" src="{unit_rel}"></iframe>
  <script>
    function show(which) {{
      const tabs = document.querySelectorAll('.tab');
      tabs.forEach(t => t.classList.remove('active'));
      if (which === 'unit') tabs[0].classList.add('active');
      if (which === 'system') tabs[1].classList.add('active');
      if (which === 'combined') tabs[2].classList.add('active');
      const frame = document.getElementById('frame');
      if (which === 'unit') frame.src = '{unit_rel}';
      if (which === 'system') frame.src = '{system_rel}';
      if (which === 'combined') frame.src = '{combined_rel}';
    }}
  </script>
</body>
</html>
"""
    out = root / "coverage_summary.html"
    out.write_text(html, encoding="utf-8")
    return out


def handle_args():
    parser = argparse.ArgumentParser(
        prog='results_processing',
        description='Convert JUnit XML to CSV or generate coverage summary index.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--junit', help='Path to JUnit XML input.')
    parser.add_argument('--csv', help='Path to CSV output.')
    parser.add_argument('--coverage-index', action='store_true', help='Generate coverage summary HTML with tabs.')
    parser.add_argument('--unit', default='htmlcov-unit', help='Unit coverage HTML directory.')
    parser.add_argument('--system', default='htmlcov-system', help='System coverage HTML directory.')
    parser.add_argument('--combined', default='htmlcov', help='Combined coverage HTML directory.')
    parser.add_argument('--out', default='summary', help='Output directory for coverage summary HTML.')
    parser.add_argument('--coverage-xml', help='Path to coverage XML report (coverage xml).')
    parser.add_argument('--coverage-csv', help='Path to coverage CSV output.')
    return parser.parse_args()


def main():
    args = handle_args()
    if args.coverage_index:
        out = generate_coverage_index(Path(args.out), Path(args.unit), Path(args.system), Path(args.combined))
        print(f'Wrote coverage summary => {out}')
        return
    if args.junit and args.csv:
        rows = parse_junit_to_rows(Path(args.junit))
        write_csv(rows, Path(args.csv))
        print(f'Wrote CSV => {args.csv}')
        return
    if args.coverage_xml and args.coverage_csv:
        rows = parse_coverage_xml(Path(args.coverage_xml))
        write_coverage_csv(rows, Path(args.coverage_csv))
        print(f'Wrote coverage CSV => {args.coverage_csv}')
        return
    print('No action performed. Provide --junit/--csv for CSV conversion or --coverage-index for summary.')


if __name__ == '__main__':
    main()
