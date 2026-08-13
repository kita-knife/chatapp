/**
 * Settings page is reserved for future use. Default selections (UI
 * language, agent mode, model) are configured directly in the chat input
 * bar — see `useChat.ts` and `ChatInput.tsx`.
 */
export function SettingsPage() {
  return (
    <div className="placeholder-page">
      <h1>Settings</h1>
      <p>
        Configure defaults in the chat input bar (language · mode · model).
        This page is reserved for future settings.
      </p>
    </div>
  );
}
