"""Rebuild both submission PDFs from their integrated Markdown sources, offline.

Follow-up and extended TC-14 material belongs with the relevant test cases.
No application tests run and no raw evidence or sealed archives are changed.
Requires reportlab and pypdf.
"""
from build_instructions import build as build_instructions
from build_results_report import build as build_results


def main():
    build_instructions()
    build_results()


if __name__ == '__main__':
    main()
