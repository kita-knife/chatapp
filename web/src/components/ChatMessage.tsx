import type { ChatMessage } from '../api/client';

interface Props {
  message: ChatMessage;
}

export function ChatMessageView({ message }: Props) {
  const isUser = message.role === 'user';
  return (
    <div className={`message ${isUser ? 'message-user' : 'message-assistant'}`}>
      <div className="message-role">{message.role}</div>
      <div className="message-content">{message.content || '…'}</div>
    </div>
  );
}
