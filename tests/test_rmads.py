#!/usr/bin/env python

import os
import pytest
import shlex
import subprocess
from pathlib import Path


@pytest.fixture(scope='session')
def session_tmpdir(tmpdir_factory):
    return tmpdir_factory.mktemp('session_data')


arg_test_cases = [
    ('', 'error: the following arguments are required: audiofile'),
    ('tests/foo.mp3', '"tests/foo.mp3" does not exist.'),
    ('tests/README.md', '"tests/README.md" is not a valid audio file.'),
    ('tests/withads.mp3 -t 1', 'withads_silence_1.json" does not exist. Can not toggle.')
]


@pytest.mark.args
@pytest.mark.parametrize('args, expected', arg_test_cases)
def test_args(args, expected, session_tmpdir):
    command = ['python', 'src/rmads.py', '-d',
               session_tmpdir] + shlex.split(args)
    result = subprocess.run(command,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert expected in result.stderr


split_test_cases = [
    ('tests/withads.mp3 -c', '3'),
    ('tests/withads.ogg -c', '3'),
    ('tests/allads.mp3 -c', '2'),
    ('tests/noads.mp3 -c', '0'),
    ('tests/noads.mp3 -m 0 -s 4 -c', '3'),
]


@pytest.mark.splits
@pytest.mark.parametrize('args, expected', split_test_cases)
def test_splits(args, expected):
    command = ['python', 'src/rmads.py'] + shlex.split(args)
    result = subprocess.run(command,
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.rstrip() == expected


def assert_withads_stats(result):
    assert result.returncode == 0
    assert 'Total ads = 2' in result.stdout
    assert 'Total ad time = 0:00:14 of 0:00:21 (67.8%)' in result.stdout
    assert 'Ads per minute = 5.71' in result.stdout
    assert 'Average ads = 1 per 0:00:10' in result.stdout


@pytest.mark.gpt4all
@pytest.mark.dependency()
def test_withads_gpt4all(session_tmpdir):
    result = subprocess.run(
        ['python', 'src/rmads.py', 'tests/withads.mp3', '-d', session_tmpdir], capture_output=True, text=True)
    assert_withads_stats(result)


@pytest.mark.gpt4all
@pytest.mark.dependency(depends=['test_withads_gpt4all'])
def test_withads_keyword(session_tmpdir):
    keypath = Path("%s/keywords.txt" % session_tmpdir).resolve()
    findtxt = 'in a wood'
    keypath.write_text(findtxt + '\n')
    result = subprocess.run(
        ['python', 'src/rmads.py',
         'tests/withads.mp3', '-d', session_tmpdir, '-k', keypath], capture_output=True, text=True)
    assert 'Identified ad keyword "%s" in "withads_silence_2.txt". Setting response to YES.' % findtxt in result.stdout
    assert 'Total ads = 3' in result.stdout


@pytest.mark.gpt4all
@pytest.mark.dependency(depends=['test_withads_gpt4all'])
def test_withads_retry(session_tmpdir):
    result = subprocess.run(
        ['python', 'src/rmads.py',
         'tests/withads.mp3', '-d', session_tmpdir, '-r', '2'], capture_output=True, text=True)
    assert 'Generating text from "withads_silence_2.mp3"' in result.stdout
    assert 'Calling gpt4all using "withads_silence_2.txt"' in result.stdout
    for i in [1, 3]:
        assert 'Using response from "withads_silence_%d.json"' % i in result.stdout
    assert_withads_stats(result)


@pytest.mark.gpt4all
@pytest.mark.dependency(depends=['test_withads_gpt4all'])
def test_withads_toggle(session_tmpdir):
    command = ['python', 'src/rmads.py',
               'tests/withads.mp3', '-d', session_tmpdir, '-t', '1']
    result = subprocess.run(
        command, capture_output=True, text=True)
    assert 'Total ads = 1' in result.stdout
    result = subprocess.run(
        command, capture_output=True, text=True)
    assert_withads_stats(result)


@pytest.mark.gemini
@pytest.mark.skipif(not os.path.exists('.env'), reason='.env file not found')
def test_withads_gemini(tmp_path):
    result = subprocess.run(
        ['python', 'src/rmads.py', 'tests/withads.mp3', '-d', tmp_path, '-g', 'gemini-pro'], capture_output=True, text=True)
    assert_withads_stats(result)
