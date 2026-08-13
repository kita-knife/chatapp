import type { ChatTurn, ToolCallEvent, ToolResultEvent } from '@/api/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface Props {
  turn: ChatTurn;
}

export function ChatTurnView({ turn }: Props) {
  const meta: string[] = [];
  if (turn.user_tokens_in > 0) meta.push(`in ${turn.user_tokens_in}`);
  if (turn.assistant_tokens_out > 0) meta.push(`out ${turn.assistant_tokens_out}`);
  return (
    <div className={`turn turn-${turn.status}`}>
      <div className="turn-row user-row">
        <div className="turn-label">user</div>
        <div className="turn-content">{turn.user_content}</div>
      </div>
      <div className="turn-row assistant-row">
        <div className="turn-label">
          assistant
          {turn.status === 'streaming' && <span className="turn-status">streaming…</span>}
          {turn.status === 'error' && <span className="turn-status error">error</span>}
          {turn.status === 'interrupted' && <span className="turn-status">interrupted</span>}
          {meta.length > 0 && <span className="turn-tokens">{meta.join(' · ')}</span>}
        </div>
        <div className="turn-content">
          {(turn.tool_calls ?? []).length > 0 && (
            <ToolTrace calls={turn.tool_calls ?? []} results={turn.tool_results ?? []} />
          )}
          {turn.assistant_content ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ ...props }) => (
                  <a {...props} target="_blank" rel="noopener noreferrer" />
                ),
              }}
            >
              {turn.assistant_content}
            </ReactMarkdown>
          ) : (
            (turn.tool_calls ?? []).length === 0 && '…'
          )}
        </div>
      </div>
    </div>
  );
}

function ToolTrace({
  calls,
  results,
}: {
  calls: ToolCallEvent[];
  results: ToolResultEvent[];
}) {
  return (
    <details className="tool-trace">
      <summary>
        🔧 {calls.length} tool {calls.length === 1 ? 'call' : 'calls'}
      </summary>
      <ol className="tool-list">
        {calls.map((c) => {
          const r = results.find((rr) => rr.tool_call_id === c.id);
          return (
            <li key={c.id}>
              <div className="tool-name">{c.name}</div>
              <pre className="tool-args">{JSON.stringify(c.arguments, null, 2)}</pre>
              {r && (
                <pre className="tool-result">{r.result}</pre>
              )}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
