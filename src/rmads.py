#!/usr/bin/env python

# Requirements:
#   sudo dnf install python3-pip mp3splt ffmpeg OR sudo apt install python3-pip mp3splt ffmpeg
#   pip install -U -r requirements.txt
#
#   To use gemini, you must have a Gemini API key (https://aistudio.google.com/app/apikey)
#   defined as GEMINI_API_KEY="YOUR_API_KEY" in an .env file

import argparse
import datetime
import glob
import google.generativeai as genai
import json
import os
import re
import shlex
import shutil
import sox
import subprocess
import sys
import tempfile
import time
import whisper
from dotenv import load_dotenv
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from gpt4all import GPT4All
from pathlib import Path


def get_args():
    global SPLITCHG
    SPLITCHG = 'Change -e, -m or -s to adjust number of split files. '
    WHISPCHG = 'Change -w to adjust audio to text recognition. '
    LLMCHG = 'Change -a or -g to adjust ad recognition. '

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                                     description='rmads is a CLI for removing ads from audio files to quantify ad statistics',
                                     epilog=SPLITCHG + WHISPCHG + LLMCHG)
    parser.add_argument('audiofiles', metavar='audiofile',
                        nargs='+', help='audio file to remove ads from')
    # https://docs.gpt4all.io/gpt4all_python/home.html#load-llm
    parser.add_argument('-a', '--gpt4all', default='Meta-Llama-3-8B-Instruct.Q4_0.gguf', choices=['Meta-Llama-3-8B-Instruct.Q4_0.gguf', 'Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf', 'Phi-3-mini-4k-instruct.Q4_0.gguf', 'orca-mini-3b-gguf2-q4_0.gguf', 'gpt4all-13b-snoozy-q4_0.gguf'],
                        help='gpt4all model to use for ad recognition')
    parser.add_argument('-c', '--count',
                        action='store_true', help='count the number of split files created and then exit')
    parser.add_argument('-d', '--dir', default='.', metavar='DIRECTORY',
                        help='working directory')
    parser.add_argument('-e', '--th', type=int, default=-48, metavar='THRESHOLD',
                        help='dB threshold level (-96 to 0) for silence when splitting audio')
    # https://ai.google.dev/gemini-api/docs/models/gemini#model-variations
    parser.add_argument('-g', '--gemini', choices=['gemini-pro', 'gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-2.0-flash'],
                        help='gemini model to use for ad recognition')
    parser.add_argument('-G', '--gemini-audio', choices=['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-2.0-flash'],
                        help='gemini model to use for audio upload ad recognition')
    parser.add_argument('-k', '--keyword-file', default=None, metavar='keywords.txt',
                        help='line separated keyword file to use to id an ad')
    parser.add_argument('-l', '--lang', default='en', metavar='LANGUAGE',
                        help='language to use for audio to text')
    parser.add_argument('-m', '--min', type=float, default=1.0, metavar='SECONDS',
                        help='minimum seconds (> 0.0) to be considered valid silence when splitting audio')
    parser.add_argument('-p', '--purge', action='store_true',
                        help='purge all progress files of file arg')
    parser.add_argument('-P', '--purge-all', action='store_true',
                        help='purge all progress files')
    parser.add_argument('-r', '--retry', nargs='*', metavar='SEGMENT',
                        help='split segment to retry (01, 02, ...)')
    parser.add_argument('--rpm', type=int, default=None,
                        help='override requests per minute when making API calls')
    parser.add_argument('-s', '--shots', type=int, default=25,
                        help='shots (> 0) of non silence when splitting audio')
    parser.add_argument('-t', '--toggle', nargs='*', metavar='SEGMENT',
                        help='split segment to toggle ad (01, 02, ...)')
    # https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages
    parser.add_argument('-w', '--whisper', default='base.en', choices=['tiny', 'tiny.en', 'base', 'base.en', 'small',
                        'small.en', 'medium', 'medium.en', 'large'], help='whisper model to use for text recognition')
    parser.add_argument('-v', '--verbose', default=None,
                        action='store_true', help='verbose output')

    return parser.parse_args()


def get_split_command(args, dir, filepath):
    quiet = ''
    if args.verbose is None or args.verbose is False:
        quiet = '-Q'
    return 'mp3splt -s -p rm=0_%.1f,min=%.1f,shots=%d,th=%d -d "%s" "%s" %s' % (
        args.min, args.min, args.shots, args.th, dir, filepath, quiet)


def get_concat_command(concatpath, filepath):
    return 'ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "%s" -c copy "%s"' % (
        concatpath, filepath)


def get_ads_stats(audiofile, adcount, noadsfile=None):
    audiodt = datetime.timedelta(milliseconds=int(
        sox.file_info.duration(audiofile)*1000))

    if noadsfile is None:
        noadsdt = datetime.timedelta(milliseconds=0)
    else:
        noadsdt = datetime.timedelta(milliseconds=int(
            sox.file_info.duration(noadsfile)*1000))

    adsdt = audiodt - noadsdt
    adspermin = adcount / (audiodt.seconds / 60)
    adspercent = 0
    avgadsdt = 0
    if adcount > 0:
        adspercent = float(100-noadsdt/audiodt*100)
        avgadsdt = audiodt/adcount

    stats = SEP + '\n'
    stats += 'Total ads = %d\n' % adcount
    # // 1000000 * 1000000 -> floor division to round to seconds
    stats += 'Total ad time = %s of %s (%.1f%%)\n' % (
        adsdt // 1000000 * 1000000, audiodt // 1000000 * 1000000, adspercent)
    stats += 'Ads per minute = %.2f\n' % adspermin
    if adcount > 0:
        stats += 'Average ads = 1 per %s\n' % (avgadsdt // 1000000 * 1000000)

    return stats


def get_noads_file(audiofile, dir, concatstr):
    noadsaudio = None
    if concatstr:
        audiobase = Path(audiofile).stem
        audioext = Path(audiofile).suffix
        concatpath = Path("%s/%s_noads.txt" %
                          (dir, audiobase)).resolve()
        concatpath.write_text(concatstr)
        noadsaudio = str(Path("%s/%s_noads%s" %
                              (dir, audiobase, audioext)).resolve())
        ffmpeg = get_concat_command(concatpath, noadsaudio)
        process = subprocess.Popen(shlex.split(ffmpeg), cwd=dir)
        process.wait()
        concatpath.unlink()

    return noadsaudio


# https://ai.google.dev/gemini-api/docs/safety-settings
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
}

# https://ai.google.dev/api/generate-content#generationconfig
GENERATION_CONFIG = genai.types.GenerationConfig(
    # https://ai.google.dev/gemini-api/docs/models/generative-models#model-parameters
    temperature=0.0,
    top_k=40,
    top_p=0.95,
    max_output_tokens=4,
    response_mime_type='text/plain')


def gemini_audio(args, audiofile, adslog=None, noadslog=None):

    gemini_audio_file = None
    print('Calling gemini using "%s"...' % audiofile)

    outlog = 'audio="%s" llm="%s"\n\n' % (audiofile, args.gemini_audio)
    if adslog:
        adslog.write(outlog)
        adslog.flush()
    if noadslog:
        noadslog.write(outlog)
        noadslog.flush()

    try:
        audiobase = Path(audiofile).stem
        # File name may only contain lowercase alphanumeric characters or dashes
        name = re.sub("[^A-Za-z0-9/-]", "",
                      audiobase.replace('_', '-')).lower()
        # can not be more than 40 characters
        name = name[:40]
        # can not begin or end with dash
        name = name.lstrip('-').rstrip('-')

        if args.purge:
            gemini_audio_file = genai.get_file(name)
            genai.delete_file(gemini_audio_file)
            print('Purged "%s" in gemini audio' %
                  gemini_audio_file.display_name)

        if args.purge_all:
            for f in genai.list_files():
                genai.delete_file(f)
                print('Purged "%s" in gemini audio' % f.display_name)

        gemini_audio_file = genai.get_file(name)
    except:
        gemini_audio_file = genai.upload_file(path=audiofile, name=name)

    if args.verbose:
        print(gemini_audio_file)

    try:
        instruction = 'Provide only timestamps ranges in the format "%H:%M:%S.%f %H:%M:%S.%f"'
        prompts = [
            'What are the timestamps for the segments of this audio that do not contain advertisements?',
        ]

        model = genai.GenerativeModel(
            args.gemini_audio, system_instruction=instruction)

        if args.verbose:
            print(str(model.count_tokens([gemini_audio_file])))

        audio_generation_config = GENERATION_CONFIG
        audio_generation_config.max_output_tokens = 8096
        response = model.generate_content(
            [prompts[0], gemini_audio_file],
            safety_settings=SAFETY_SETTINGS,
            generation_config=audio_generation_config)

        concatstr = ''
        fullpath = str(Path(audiofile).resolve())

        print('Response =')

        lines = response.text.splitlines()
        for line in lines:

            values = line.split(' ', maxsplit=2)
            if len(values) != 2:
                continue

            start = values[0]
            end = values[1]

            outlog = '%s %s - not ad' % (start, end)
            if noadslog:
                noadslog.write(outlog + '\n')
            print(outlog)

            concatstr += "file '%s'\n" % fullpath
            concatstr += 'inpoint %s\n' % start
            concatstr += 'outpoint %s\n' % end

        noadsaudio = get_noads_file(audiofile, args.dir, concatstr)

    except Exception as e:
        print(e, file=sys.stderr)
        exit(1)

    try:
        instruction = 'Provide only an integer'
        prompt = 'How many separate advertisements are in this audio?'

        model = genai.GenerativeModel(
            args.gemini_audio, system_instruction=instruction)

        response = model.generate_content(
            [prompt, gemini_audio_file],
            safety_settings=SAFETY_SETTINGS,
            generation_config=GENERATION_CONFIG)

        count = int(response.text)
        adsout = get_ads_stats(audiofile, count, noadsaudio)
        if adslog:
            adslog.write(adsout)
        print(adsout)

        if noadslog:
            noadsout = SEP + '\n'
            noadsout += 'Total no ads = %d\n' % count
            noadslog.write(noadsout)

    except Exception as e:
        print(e, file=sys.stderr)
        exit(1)


def main(args=None):

    global SEP
    SEP = '=========='
    SPLITDIR = 'mp3splt'
    WHISPDIR = 'whisper'
    LLMDIR = 'llm'

    args = get_args()

    # Check if audio exists
    for audiofile in args.audiofiles:
        if not Path(audiofile).is_file():
            print('"%s" does not exist.' % audiofile, file=sys.stderr)
            exit(1)

    keywords = None
    if args.keyword_file:
        if not Path(args.keyword_file).is_file():
            print('"%s" does not exist.' % args.keyword_file, file=sys.stderr)
            exit(1)
        with open(args.keyword_file, 'r') as f:
            keywords = set(keyword.strip().lower() for keyword in f)

    if Path(args.dir).is_dir() is not True:
        Path(args.dir).mkdir(parents=True, exist_ok=True)

    splitdir = args.dir + '/' + SPLITDIR
    whispdir = args.dir + '/' + WHISPDIR
    llmdir = args.dir + '/' + LLMDIR

    if args.purge_all and not args.gemini_audio:
        shutil.rmtree(splitdir, ignore_errors=True)
        shutil.rmtree(whispdir, ignore_errors=True)
        shutil.rmtree(llmdir, ignore_errors=True)
        if args.verbose:
            print("Removed %s" % splitdir)
            print("Removed %s" % whispdir)
            print("Removed %s" % llmdir)
        for path in Path(args.dir).glob('mp3splt.log'):
            path.unlink()
            if args.verbose:
                print("Removed %s" % path)
        for path in Path(args.dir).glob('*ads.log'):
            path.unlink()
            if args.verbose:
                print("Removed %s" % path)

        for path in Path(args.dir).glob('*noads*'):
            path.unlink()
            if args.verbose:
                print("Removed %s" % path)

        print('Purged all progress files in "%s"' % args.dir)

    if args.purge and not args.gemini_audio:
        for audiofile in args.audiofiles:
            audiobase = glob.escape(Path(audiofile).stem)
            audioext = Path(audiofile).suffix
            for path in Path(splitdir).glob('%s*%s' % (audiobase, audioext)):
                path.unlink()
                if args.verbose:
                    print("Removed %s" % path)
            for path in Path(args.dir).glob('mp3splt.log'):
                path.unlink()
                if args.verbose:
                    print("Removed %s" % path)
            for path in Path(whispdir).glob('%s*.txt' % audiobase):
                path.unlink()
                if args.verbose:
                    print("Removed %s" % path)
            for path in Path(llmdir).glob('%s*.json' % audiobase):
                path.unlink()
                if args.verbose:
                    print("Removed %s" % path)
            for path in Path(args.dir).glob('%s*ads.log' % audiobase):
                path.unlink()
                if args.verbose:
                    print("Removed %s" % path)
            for path in Path(args.dir).glob('%s*noads%s' % (audiobase, audioext)):
                path.unlink()
                if args.verbose:
                    print("Removed %s" % path)

            print('Purged "%s" progress files in "%s"' % (audiofile, args.dir))

    if args.count:
        for audiofile in args.audiofiles:
            with tempfile.TemporaryDirectory() as tempdir:

                command = get_split_command(
                    args, tempdir, Path(audiofile).resolve())
                process = subprocess.Popen(
                    shlex.split(command), cwd=tempdir)
                process.wait()

                # Count number of split files
                pattern = '%s*%s' % (glob.escape(Path(audiofile).stem),
                                     Path(audiofile).suffix)
                count = 0
                for path in Path(tempdir).glob(pattern):
                    count += 1
                print(count)

        exit(0)

    # Retry a specific segment
    if not args.retry == None:
        for retry in args.retry:
            for audiofile in args.audiofiles:
                txtpath = Path('%s/%s_silence_%s.txt' %
                               (whispdir, Path(audiofile).stem, retry))
                txtpath.unlink(missing_ok=True)
                jsonpath = Path('%s/%s_silence_%s.json' %
                                (llmdir, Path(audiofile).stem, retry))
                jsonpath.unlink(missing_ok=True)

    # Toggle a specific segment (change YES to NO or NO to YES)
    if not args.toggle == None:
        for toggle in args.toggle:
            for audiofile in args.audiofiles:

                jsonfile = '%s/%s_silence_%s.json' % (
                    llmdir, Path(audiofile).stem, toggle)

                if not Path(jsonfile).is_file():
                    print('"%s" does not exist. Can not toggle.' %
                          jsonfile, file=sys.stderr)
                    exit(1)

                with open(jsonfile, 'r') as f:
                    data = json.load(f)

                if data['response'].casefold().startswith('YES'.casefold()):
                    data['response'] = 'NO'
                else:
                    data['response'] = 'YES'
                data['toggled'] = True

                with open(jsonfile, 'w') as f:
                    json.dump(data, f, indent=2)

    llm = args.gpt4all
    if args.gemini or args.gemini_audio:
        GEMINI_KEY = "GEMINI_API_KEY"
        load_dotenv()
        if GEMINI_KEY in os.environ:
            genai.configure(api_key=os.environ[GEMINI_KEY])
            llm = args.gemini
        else:
            print(
                '%s not found. You must have a Gemini API key from (https://aistudio.google.com/app/apikey) defined as %s="YOUR_API_KEY" in an .env file' % (GEMINI_KEY, GEMINI_KEY), file=sys.stderr)
            exit(1)

    if not args.gemini_audio:
        Path(splitdir).mkdir(parents=True, exist_ok=True)
        Path(whispdir).mkdir(parents=True, exist_ok=True)
        Path(llmdir).mkdir(parents=True, exist_ok=True)

    for audiofile in args.audiofiles:

        ads = 0
        concatstr = ''
        audiobase = Path(audiofile).stem
        audioext = Path(audiofile).suffix
        adslog = Path("%s/%s_ads.log" % (args.dir, audiobase)).open("a")
        adslog.truncate(0)
        noadslog = Path("%s/%s_noads.log" % (args.dir, audiobase)).open("a")
        noadslog.truncate(0)

        if args.gemini_audio:
            gemini_audio(args, audiofile, adslog, noadslog)
            continue

        command = get_split_command(args, SPLITDIR, Path(audiofile).resolve())
        process = subprocess.Popen(shlex.split(command), cwd=args.dir)
        returncode = process.wait()
        if returncode != 0:
            print('"%s" is not a valid audio file.' %
                  audiofile, file=sys.stderr)
            exit(1)

        # Count number of split files
        pattern = '%s*%s' % (glob.escape(audiobase), audioext)
        count = 0
        for path in Path(splitdir).glob(pattern):
            count += 1
        outlog = 'audio="%s" min=%s shots=%s th=%s splits=%d whisper="%s" llm="%s"' % (
            audiofile, args.min, args.shots, args.th, count, args.whisper, llm)
        print(outlog)
        if count <= 0:
            print('No split files created. %s\n' % SPLITCHG, file=sys.stderr)
            continue

        noadslog.write(outlog + '\n\n')
        noadslog.flush()

        adslog.write(outlog + '\n\n')
        adslog.flush()

        # Iterate over split files
        for path in Path(splitdir).glob(pattern):

            print(SEP)

            start = time.time()
            splitbase = path.stem

            # Generate text from audio
            txtpath = Path("%s/%s.txt" % (whispdir, splitbase))
            if not txtpath.is_file():
                print('Generating text from "%s"...' % path.name)
                model = whisper.load_model(args.whisper)
                result = model.transcribe(
                    str(path), language=args.lang, fp16=False, verbose=args.verbose)
                txtpath.write_text(result["text"])

            if txtpath.is_file():
                jsonpath = Path("%s/%s.json" % (llmdir, splitbase))

                # Check for ad keywords
                if keywords:
                    splittxt = txtpath.read_text().lower()
                    for keyword in keywords:
                        if re.search(r'\b' + keyword + r'\b', splittxt):
                            print('Identified ad keyword "%s" in "%s.txt". Setting response to YES.' %
                                  (keyword, splitbase))
                            jsonpath.write_text(json.dumps(
                                {'llm': 'keyword', 'keyword': '%s' % keyword, 'response': 'YES'}, indent=2))
                            break

                # Generate response json from text
                if not jsonpath.is_file():

                    INSTRUCTION = 'You are an advertising agency.'
                    prompt = 'Answer with YES or NO. Is the following text an advertisement: %s' % txtpath.read_text()

                    if llm == args.gemini:

                        # Requests per minute for gemini (https://ai.google.dev/gemini-api/docs/rate-limits)
                        if args.gemini == 'gemini-1.5-pro':
                            rpm = 2
                        else:
                            rpm = 15

                        # Override rpm
                        if args.rpm is not None:
                            rpm = args.rpm

                        duration = time.time()-start
                        sleep = 60/rpm
                        if duration < sleep:
                            wait = sleep - duration
                            print(
                                'Waiting for %.1f seconds to call %s because rpm = %d' % (wait, args.gemini, rpm))
                            time.sleep(sleep)

                        # https://ai.google.dev/api/generate-content
                        if args.gemini == 'gemini-pro':
                            model = genai.GenerativeModel(args.gemini)
                        else:
                            model = genai.GenerativeModel(
                                args.gemini, system_instruction=INSTRUCTION)

                        print('Calling gemini using "%s.txt"...' %
                              splitbase)

                        try:
                            response = model.generate_content(
                                prompt,
                                safety_settings=SAFETY_SETTINGS,
                                generation_config=GENERATION_CONFIG)
                            jsonpath.write_text(json.dumps(
                                {'llm': '%s' % llm, 'response': '%s' % response.text}, indent=2))

                        except Exception as e:
                            print(e, file=sys.stderr)
                            exit(1)

                    else:
                        # https://docs.gpt4all.io/gpt4all_python/ref.html
                        print('Calling gpt4all using "%s.txt"...' %
                              splitbase)
                        model = GPT4All(args.gpt4all)
                        with model.chat_session(system_prompt=INSTRUCTION):
                            out = model.generate(prompt, max_tokens=1024)
                            jsonpath.write_text(json.dumps(
                                {'llm': '%s' % llm, 'response': '%s' % out}, indent=2))

                else:
                    print('Using response from "%s.json"' %
                          splitbase)

            # Parse json for text = YES or NO
            if jsonpath.is_file():
                txtfilelog = "%s %s.txt %s\n%s\n\n" % (
                    SEP, path.stem, SEP, txtpath.read_text())
                data = json.loads(jsonpath.read_text())
                response = data['response']
                if response.casefold().startswith('YES'.casefold()):
                    ads = ads+1
                    adslog.write(txtfilelog)
                    adslog.flush()
                else:
                    noadslog.write(txtfilelog)
                    noadslog.flush()
                    concatstr += "file '%s'\n" % str(path.resolve())
                print('Response = %s' % response)

        noadsaudio = get_noads_file(audiofile, args.dir, concatstr)

        adsout = get_ads_stats(audiofile, ads, noadsaudio)

        adslog.write(adsout)
        print(adsout)

        noadsout = SEP + '\n'
        noadsout += 'Total no ads = %d\n' % (count - ads)
        noadslog.write(noadsout)


if __name__ == '__main__':
    main()
