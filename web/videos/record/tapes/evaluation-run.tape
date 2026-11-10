# The evaluation video's first run: the dry run's summary, then the run itself, in ~/demo/tally.
#   vhs record/tapes/evaluation-run.tape   (from web/videos/)
Output public/clips/e-run.mp4
Set Shell bash
Set FontSize 20
Set FontFamily "IBM Plex Mono"
Set Width 1680
Set Height 860
Set Framerate 15
Set Padding 24
Set CursorBlink false
Set TypingSpeed 45ms
Set WaitTimeout 30m
Set WaitPattern /tally \$\s*$/
Set Theme {"name":"nock","background":"#15131d","foreground":"#f1eefa","cursor":"#8fe9ff","selection":"#3a3550","black":"#15131d","red":"#ff7a90","green":"#9be8b4","yellow":"#ffe27a","blue":"#8fb8ff","magenta":"#ff9ad5","cyan":"#8fe9ff","white":"#f1eefa","brightBlack":"#6e6888","brightRed":"#ff9aab","brightGreen":"#b8f5d0","brightYellow":"#fff2a0","brightBlue":"#b9c8ff","brightMagenta":"#ffb0d6","brightCyan":"#bff3ff","brightWhite":"#ffffff"}
Hide
Type "cd ~/demo/tally && export PS1='tally $ ' && clear"
Enter
Sleep 1s
Show
Sleep 1s
Type ".nock/nock eval run --dry | tail -6"
Sleep 400ms
Enter
Wait
Sleep 2s
Type ".nock/nock eval run --budget 1"
Sleep 400ms
Enter
Wait
Sleep 4s
