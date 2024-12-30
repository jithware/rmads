# rmads
rmads is a CLI for removing ads from audio files to quantify ad statistics

## Install
``` sudo dnf install python3-pip mp3splt ffmpeg``` OR ```sudo apt install python3-pip mp3splt ffmpeg```

``` pip install -U -r requirements.txt```

To use gemini, you must have a [Gemini API key](https://aistudio.google.com/app/apikey)
defined as ```GEMINI_API_KEY="YOUR_API_KEY"``` in an ```.env``` file

## Test
```pytest -v```

## Usage
```
usage: rmads.py [-h]
                [-a {Meta-Llama-3-8B-Instruct.Q4_0.gguf,Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf,Phi-3-mini-4k-instruct.Q4_0.gguf,orca-mini-3b-gguf2-q4_0.gguf,gpt4all-13b-snoozy-q4_0.gguf}]
                [-c] [-d DIRECTORY] [-e THRESHOLD]
                [-g {gemini-pro,gemini-1.0-pro,gemini-1.5-pro,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-2.0-flash-exp}]
                [-G {gemini-1.5-pro,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-2.0-flash-exp}] [-k keywords.txt]
                [-l LANGUAGE] [-m SECONDS] [-p] [-P] [-r [SEGMENT ...]] [--rpm RPM] [-s SHOTS] [-t [SEGMENT ...]]
                [-w {tiny,tiny.en,base,base.en,small,small.en,medium,medium.en,large}] [-v]
                audiofile [audiofile ...]

rmads is a CLI for removing ads from audio files to quantify ad statistics

positional arguments:
  audiofile             audio file to remove ads from

options:
  -h, --help            show this help message and exit
  -a {Meta-Llama-3-8B-Instruct.Q4_0.gguf,Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf,Phi-3-mini-4k-instruct.Q4_0.gguf,orca-mini-3b-gguf2-q4_0.gguf,gpt4all-13b-snoozy-q4_0.gguf}, --gpt4all {Meta-Llama-3-8B-Instruct.Q4_0.gguf,Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf,Phi-3-mini-4k-instruct.Q4_0.gguf,orca-mini-3b-gguf2-q4_0.gguf,gpt4all-13b-snoozy-q4_0.gguf}
                        gpt4all model to use for ad recognition (default: Meta-Llama-3-8B-Instruct.Q4_0.gguf)
  -c, --count           count the number of split files created and then exit (default: False)
  -d DIRECTORY, --dir DIRECTORY
                        working directory (default: .)
  -e THRESHOLD, --th THRESHOLD
                        dB threshold level (-96 to 0) for silence when splitting audio (default: -48)
  -g {gemini-pro,gemini-1.0-pro,gemini-1.5-pro,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-2.0-flash-exp}, --gemini {gemini-pro,gemini-1.0-pro,gemini-1.5-pro,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-2.0-flash-exp}
                        gemini model to use for ad recognition (default: None)
  -G {gemini-1.5-pro,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-2.0-flash-exp}, --gemini-audio {gemini-1.5-pro,gemini-1.5-flash,gemini-1.5-flash-8b,gemini-2.0-flash-exp}
                        gemini model to use for audio upload ad recognition (default: None)
  -k keywords.txt, --keyword-file keywords.txt
                        line separated keyword file to use to id an ad (default: None)
  -l LANGUAGE, --lang LANGUAGE
                        language to use for audio to text (default: en)
  -m SECONDS, --min SECONDS
                        minimum seconds (> 0.0) to be considered valid silence when splitting audio (default: 1.0)
  -p, --purge           purge all progress files of file arg (default: False)
  -P, --purge-all       purge all progress files (default: False)
  -r [SEGMENT ...], --retry [SEGMENT ...]
                        split segment to retry (01, 02, ...) (default: None)
  --rpm RPM             override requests per minute when making API calls (default: None)
  -s SHOTS, --shots SHOTS
                        shots (> 0) of non silence when splitting audio (default: 25)
  -t [SEGMENT ...], --toggle [SEGMENT ...]
                        split segment to toggle ad (01, 02, ...) (default: None)
  -w {tiny,tiny.en,base,base.en,small,small.en,medium,medium.en,large}, --whisper {tiny,tiny.en,base,base.en,small,small.en,medium,medium.en,large}
                        whisper model to use for text recognition (default: base.en)
  -v, --verbose         verbose output (default: None)

Change -e, -m or -s to adjust number of split files. Change -w to adjust audio to text recognition. Change -a or -g to
adjust ad recognition.
```

## Examples
```
./src/rmads.py -d tmp tests/road_not_taken.mp3 
audio="tests/road_not_taken.mp3" min=1.0 shots=25 th=-48 splits=5 whisper="base.en" llm="Meta-Llama-3-8B-Instruct.Q4_0.gguf"
==========
Generating text from "road_not_taken_silence_01.mp3"...
Calling gpt4all using "road_not_taken_silence_01.txt"...
Response = YES
==========
Generating text from "road_not_taken_silence_02.mp3"...
Calling gpt4all using "road_not_taken_silence_02.txt"...
Response = NO
==========
Generating text from "road_not_taken_silence_03.mp3"...
Calling gpt4all using "road_not_taken_silence_03.txt"...
Response = YES
==========
Generating text from "road_not_taken_silence_04.mp3"...
Calling gpt4all using "road_not_taken_silence_04.txt"...
Response = NO
==========
Generating text from "road_not_taken_silence_05.mp3"...
Calling gpt4all using "road_not_taken_silence_05.txt"...
Response = NO
==========
Total ads = 2
Total ad time = 0:00:16 of 0:00:59 (27.5%)
Ads per minute = 2.03
Average ads = 1 per 0:00:29
```

```
./src/rmads.py -d tmp tests/road_not_taken.mp3 -p -g gemini-pro
Purged "tests/road_not_taken.mp3" progress files in "tmp"
audio="tests/road_not_taken.mp3" min=1.0 shots=25 th=-48 splits=5 whisper="base.en" llm="gemini-pro"
==========
Generating text from "road_not_taken_silence_01.mp3"...
Calling gemini using "road_not_taken_silence_01.txt"...
Response = YES
==========
Generating text from "road_not_taken_silence_02.mp3"...
Calling gemini using "road_not_taken_silence_02.txt"...
Response = NO
==========
Generating text from "road_not_taken_silence_03.mp3"...
Waiting for 0.3 seconds to call gemini-pro because rpm = 15
Calling gemini using "road_not_taken_silence_03.txt"...
Response = YES
==========
Generating text from "road_not_taken_silence_04.mp3"...
Waiting for 0.3 seconds to call gemini-pro because rpm = 15
Calling gemini using "road_not_taken_silence_04.txt"...
Response = NO
==========
Generating text from "road_not_taken_silence_05.mp3"...
Calling gemini using "road_not_taken_silence_05.txt"...
Response = NO
==========
Total ads = 2
Total ad time = 0:00:16 of 0:00:59 (27.5%)
Ads per minute = 2.03
Average ads = 1 per 0:00:29
```