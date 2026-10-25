# Moss command accuracy (measured)

60 seeded phrasings per command (clear commands and loose paraphrases), plus 60 ordinary sentences that must NOT trigger anything.

| Command | Phrasings | Strict matcher | Strict + Gemma fallback |
|---|---|---|---|
| recycle | 60 | 57% | not run |
| note | 60 | 67% | not run |
| next | 60 | 57% | not run |
| previous | 60 | 58% | not run |
| volume_up | 60 | 70% | not run |
| volume_down | 60 | 68% | not run |
| mute | 60 | 72% | not run |
| read_notes | 60 | 85% | not run |
| lazy_score | 60 | 92% | not run |
| **All commands** | 540 | **69%** | not run |
| False triggers on 60 ordinary sentences | 60 | 0 | not run |

Sample misses (first few per command):

- recycle: "can you my recycle bin is full, sort it for me"
- recycle: "Moss, get rid of what is in the trash please"
- recycle: "um take out the trash on my computer now"
- recycle: "okay I need the recycle bin cleaned out thanks"
- note: "um put a note in my notepad"
- note: "yo put a note in my notepad now"
- note: "yo write something down for me now"
- note: "Moss can you I want to jot something down now"
- next: "um let's hear something else, next one for me"
- next: "Moss can you jump to the next tune"
- next: "can you flip to the following song Moss"
- next: "um I don't like this one, go to the next track please"
- previous: "um take me back to the last track now"
- previous: "Moss can you I want the earlier song again"
- previous: "Moss can you I want the earlier song again for me"
- previous: "could you please put the last track on again for me"
- volume_up: "um the sound is too quiet, raise it"
- volume_up: "Moss can you bring the volume up Moss"
- volume_up: "um I can't hear it, make it louder for me"
- volume_up: "um the sound is too quiet, raise it thanks"
- volume_down: "Moss can you bring the volume down now"
- volume_down: "Moss, it's too loud, make it quieter thanks"
- volume_down: "Moss, the sound is too loud, lower it Moss"
- volume_down: "hey Moss the sound is too loud, lower it"
- mute: "Moss, silence the speakers, mute them"
- mute: "could you please silence the speakers, mute them thanks"
- mute: "Moss can you mute the sound for a second Moss"
- mute: "um mute the sound for a second for me"
- read_notes: "hey Moss go over my notes for today please"
- read_notes: "yo read me what I wrote down today"
- read_notes: "can you read me what I wrote down today for me"
- read_notes: "um read me what I wrote down today please"
- lazy_score: "can you what did you do for me please"
- lazy_score: "what did you do for me Moss"
- lazy_score: "could you please what did you do for me Moss"
- lazy_score: "um what did you do for me please"
