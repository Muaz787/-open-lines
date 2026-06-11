export function TranscriptLines({ text }: { text: string }) {
  return (
    <div className="db-transcript">
      {text.split('\n').filter(l => l.trim()).map((line, i) => {
        const isAI   = line.startsWith('AI:')
        const isUser = line.startsWith('User:')
        const speaker = isAI ? 'AI' : isUser ? 'You' : null
        const content = isAI ? line.slice(3).trim() : isUser ? line.slice(5).trim() : line
        return (
          <div key={i} className="db-transcript-line">
            {speaker && (
              <span className={`db-transcript-speaker${isAI ? ' db-transcript-speaker--ai' : ''}`}>
                {speaker}
              </span>
            )}
            {content}
          </div>
        )
      })}
    </div>
  )
}
