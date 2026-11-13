# Local speech engine notices

Status: Active
Last reviewed: 10 November 2026

The Whisper engine builds the verified whisper.cpp release source under its MIT
license. Its license is retained in the image. The separate Piper process uses
piper-tts under GPL-3.0-or-later; its installed distribution retains COPYING and
the bundled component notices. Review those terms before redistributing the image
or a derived artifact. The local POC does not publish either image.

The Piper upstream source is [Piper](https://github.com/OHF-voice/piper1-gpl), and
the selected package metadata is [piper-tts 1.8.0](https://pypi.org/project/piper-tts/1.8.0/).
The LJSpeech voice model card is retained with the pinned model cache; it identifies
the dataset as public domain. Voice-repository metadata identifies its MIT license.
Whisper weights and the Qwen model retain their separately declared model licenses
and pinned license/card files in the model manifest. Engine and model licenses
are separate facts.

All model preparation is an explicit host action. The engine containers mount
prepared models read-only, use an internal network and have no download endpoint.
Speech input, recognized text, generated text and private child diagnostics are
request-scoped files removed after completion or controlled failure. A model
response cannot grant booking mutation authority or establish human acknowledgement.
