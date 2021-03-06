#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test runner that will limit the output of tests to a result set relevant for a
particular diff in Git. That is a diff between revisions or a diff between two
branches' tips.

This test runner will work with both Python 2.7 as well as 3.x.
"""

## Created: 23 May 2015 Guy Kloss <gk@mega.co.nz>
##
## (c) 2015 by Mega Limited, Auckland, New Zealand
##     http://mega.co.nz/
##     Simplified (2-clause) BSD License.
##
## You should have received a copy of the license along with this
## program.
##
## This file is part of the multi-party chat encryption suite.
##
## This code is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

__author__ = 'Guy Kloss <gk@mega.co.nz>'

import argparse
import os
import re
import logging
import subprocess
import collections
import config

JSHINT_BIN = 'node_modules/.bin/jshint'
JSHINT_RULES = '--verbose'
JSCS_BIN = 'node_modules/.bin/jscs'
JSCS_RULES = '--verbose'
CPPCHECK_BIN = 'cppcheck'
CPPCHECK_COMMAND = ("{command}"
                    " --template={{file}};{{line}};{{severity}};{{id}};{{message}}"
                    " --enable=warning,portability,information,missingInclude"
                    " --std=c++03 --force"
                    " --quiet"
                    " -I include"
                    " -I include/mega/{platform}"
                    " src/ examples/")
PLATFORMS = {'posix': 'posix',
             'nt': 'win32'}
PROJECT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            os.path.pardir))


def get_git_line_sets(base, target):
    """
    Obtains the Git diff between the base and target to identify the lines that
    contain alterations in the target code. If branch names are given for the
    base or target, the tips of those branches are used.

    :param base: Base branch/commit for the diff.
    :param target: Target branch/commit for the diff.
    :return: A dictionary of changed line numbers. The key in the dictionary is
        the file path, the value is a set of line numbers.
    """
    # Get the Git output for the desired diff.
    logging.info('Extracting relevant lines from Git diff ...')
    command = 'git diff -U0 {} {}'.format(base, target)
    output = subprocess.check_output(command.split())
    diff = output.decode('latin1').split('\n')

    # Hunt down lines of changes for different files.
    file_line_mapping = collections.defaultdict(set)
    current_file = None
    for line in diff:
        if line.startswith('+++'):
            # Line giving target file.
            for_file = line.split()[1]
            current_file = for_file[2:]
        elif line.startswith('@@'):
            # Line giving alteration line range of diff fragment.
            target_lines = line.split()[2].split(',')
            start_line = int(target_lines[0])
            line_range = int(target_lines[1]) if len(target_lines) == 2 else 1
            # Update our lines if we have target lines.
            if line_range > 0:
                file_line_mapping[current_file].update(range(start_line,
                                                             start_line + line_range - 1))

    return file_line_mapping


def reduce_jshint(file_line_mapping, **extra):
    """
    Runs JSHint on the project with the default configured rules. The output
    is reduced to only contain entries from the Git change set.

    :param file_line_mapping: Mapping of files with changed lines (obtained
        `get_git_line_sets()`).
    :param extra: Optional keyword arguments:
        `norules`: If true, omit verbose output of violated rule identifier
                   (default: `False` to include rules).
    :return: A formatted string suitable for output.
    """
    norules = extra['norules'] if 'norules' in extra else False
    # Get the JSHint output.
    logging.info('Obtaining JSHint output ...')
    os.chdir(PROJECT_PATH)
    command = 'node {} {} .'.format(JSHINT_BIN, JSHINT_RULES if not norules else '')
    output = None
    try:
        output = subprocess.check_output(command.split())
    except subprocess.CalledProcessError as ex:
        # JSHint found something, so it has returned an error code.
        # But we still want the output in the same fashion.
        output = ex.output
    output = output.decode('utf8').split('\n')

    # Go through output and collect only relevant lines to the result.
    result = ['\nJSHint output:\n==============\n']
    jshint_expression = re.compile(r'(.+): line (\d+), col \d+, .+')
    for line in output:
        parse_result = jshint_expression.findall(line)
        # Check if we've got a relevant line.
        if parse_result:
            file_name, line_no = parse_result[0][0], int(parse_result[0][1])
            # Check if the line is part of our selection list.
            if line_no in file_line_mapping[file_name]:
                result.append(line)

    # Add the number of errors and return in a nicely formatted way.
    result.append('\n{} errors'.format(len(result) - 1))
    return '\n'.join(result)


def reduce_jscs(file_line_mapping, **extra):
    """
    Runs JSHCS on the project with the default configured rules. The output
    is reduced to only contain entries from the Git change set.

    :param file_line_mapping: Mapping of files with changed lines (obtained
        `get_git_line_sets()`).
    :param extra: Optional keyword arguments:
        `norules`: If true, omit verbose output of violated rule identifier
                   (default: `False` to include rules).
    :return: A formatted string suitable for output.
    """
    norules = extra['norules'] if 'norules' in extra else False
    # Get the JSCS output.
    logging.info('Obtaining JSCS output ...')
    os.chdir(PROJECT_PATH)
    command = 'node {} {} .'.format(JSCS_BIN, JSCS_RULES if not norules else '')
    output = None
    try:
        output = subprocess.check_output(command.split())
    except subprocess.CalledProcessError as ex:
        # JSCS found something, so it has returned an error code.
        # But we still want the output in the same fashion.
        output = ex.output
    output = output.decode('utf8').split('\n\n')

    # Go through output and collect only relevant lines to the result.
    result = ['\nJSCS output:\n============']
    lines_expression = re.compile(r'^ +(\d+) |.*(?:\n|\r\n?)-', re.MULTILINE)
    file_expression = re.compile(r'^[^\b].* \./(.+) :$', re.MULTILINE)
    for item in output:
        # Do the processing for every block here.
        line_no_candidates = lines_expression.findall(item, re.MULTILINE)
        # Check if we've got a relevant block.
        if line_no_candidates and '' in line_no_candidates:
            line_no = int(line_no_candidates[line_no_candidates.index('') - 1])
            file_name = file_expression.findall(item)[0]
            # Check if the line is part of our selection list.
            if line_no in file_line_mapping[file_name]:
                result.append(item)

    # Add the number of errors and return in a nicely formatted way.
    result.append('\n{} code style errors found.'.format(len(result) - 1))
    return '\n\n'.join(result)


def reduce_cppcheck(file_line_mapping, **extra):
    """
    Runs CppCheck on the project with the default configured rules. The output
    is reduced to only contain entries from the Git change set.

    :param file_line_mapping: Mapping of files with changed lines (obtained
        `get_git_line_sets()`).
    :param extra: Optional keyword arguments:
        `platform`: A specific platform to test for, as used in
                    `include/mega/` (default: detect local system's platform).
    :return: A formatted string suitable for output.
    """
    logging.info('Obtaining CppCheck output ...')
    platform = platform = PLATFORMS[os.name]
    if 'platform' in extra:
        # Override if given.
        platform = extra['platform']
        
    # Get the CppCheck output.
    os.chdir(PROJECT_PATH)
    command = CPPCHECK_COMMAND.format(command=CPPCHECK_BIN,
                                      platform=platform)
    output = None
    try:
        output = subprocess.check_output(command.split(),
                                         stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as ex:
        # CppCheck found something, so it has returned an error code.
        # But we still want the output in the same fashion.
        output = ex.output
    output = output.decode('utf8').split('\n')
    
    # Go through output and collect only relevant lines to the result.
    logging.debug('Reducing CppCheck output ...')
    result = ['\nCppCheck output:\n================\n']
    cppcheck_expression = re.compile(r'^(.+);(\d+);')
    for line in output:
        parse_result = cppcheck_expression.findall(line)
        # Check if we've got a relevant line.
        if parse_result:
            file_name, line_no = parse_result[0][0], int(parse_result[0][1])
            # Check if the line is part of our selection list.
            if line_no in file_line_mapping[file_name]:
                formatted = '; '.join(line.split(';'))
                result.append(formatted)

    # Add the number of errors and return in a nicely formatted way.
    result.append('\n{} errors'.format(len(result) - 1))
    return '\n'.join(result)


def main(base, target, norules):
    """
    Run the JSHint and JSCS tests and present output ont eh console via print.
    """
    CHECKER_MAPPING = {'jshint': reduce_jshint,
                       'jscs': reduce_jscs,
                       'cppcheck': reduce_cppcheck}
    
    file_line_mapping = get_git_line_sets(base, target)
    results = []
    for checker in config.checkers:
        worker = CHECKER_MAPPING[checker]
        extra_options = config.extra_options[checker]
        results.append(worker(file_line_mapping, **extra_options))
    logging.info('Output of reduced results ...')
    print('\n\n'.join(results))


if __name__ == '__main__':
    # Set up logging.
    logging.basicConfig(level=logging.DEBUG,
                        format='%(levelname)s\t%(asctime)s %(message)s')

    # Setup the command line argument parser.
    DESCRIPTION = ('Filter output from static code analyser and style checker '
                   'to only contain content relevant to a diff '
                   '(e. g. between commits or tips of branches). '
                   'This tool will filter output from JSHint and JSCS.')
    EPILOG = 'Note: if no revision (commit ID) is given, the branch tip will be used.'
    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG)
    parser.add_argument('--norules', default=False, action='store_true',
                        help="Don't show rule names with description (default: show rules names)")
    parser.add_argument('base',
                        help='base revision or name of base branch')
    parser.add_argument('target', nargs='?', default='',
                        help=('target revision or name of target branch'
                              ' (default: tip of current branch)'))

    args = parser.parse_args()

    main(args.base, args.target, args.norules)
