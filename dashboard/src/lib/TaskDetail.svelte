<script lang="ts">
  import { onMount } from 'svelte';

  interface Note {
    id: number;
    author: string;
    content: string;
    created_at: string;
  }

  interface Clarification {
    id: number;
    asked_by: string;
    question: string;
    answer: string | null;
    status: string;
    created_at: string;
  }

  interface DependencySummary {
    id: number;
    title: string;
    status: string;
  }

  interface Task {
    id: number;
    title: string;
    description: string;
    status: string;
    assigned_to: string | null;
    milestone_name: string;
    tags: string[];
    sequence_order: number;
    github_issues: number[];
    relevant_docs: string[];
    created_at: string;
    updated_at: string;
    notes: Note[];
    clarifications: Clarification[];
    blocked_by: DependencySummary[];
    blocks: DependencySummary[];
  }

  let { taskId }: { taskId: number } = $props();

  let task: Task | null = $state(null);
  let activeTab = $state<'context' | 'activity'>('context');
  let newNote = $state('');
  let noteAuthor = $state(
    (typeof localStorage !== 'undefined' && localStorage.getItem('hive_author')) ?? ''
  );
  let answerDrafts = $state<Record<number, string>>({});

  async function loadTask() {
    const res = await fetch(`/api/tasks/${taskId}`);
    if (res.ok) {
      task = (await res.json()) as Task;
    }
  }

  onMount(() => {
    void loadTask();
  });

  const pendingClarifications = $derived(
    task?.clarifications.filter((c) => c.status === 'pending') ?? []
  );

  async function postNote() {
    if (!newNote.trim() || !noteAuthor.trim()) return;
    if (typeof localStorage !== 'undefined') localStorage.setItem('hive_author', noteAuthor);
    await fetch(`/api/tasks/${taskId}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author: noteAuthor, content: newNote })
    });
    newNote = '';
    void loadTask();
  }

  async function submitAnswer(clarificationId: number) {
    const answer = answerDrafts[clarificationId] ?? '';
    if (!answer.trim()) return;
    await fetch(`/api/clarifications/${clarificationId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer })
    });
    answerDrafts = { ...answerDrafts, [clarificationId]: '' };
    void loadTask();
  }

  async function updateField(field: 'status' | 'assigned_to', value: string) {
    await fetch(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value || null })
    });
    void loadTask();
  }

  const answeredClarifications = $derived(
    task?.clarifications.filter((c) => c.status === 'answered') ?? []
  );
</script>

<div class="task-detail">
  <div class="detail-header">
    <a href="/" class="back-link">← Back to board</a>
    {#if task}
      <span class="task-id-badge">#{task.id}</span>
      <h1 class="task-title">{task.title}</h1>
    {/if}
  </div>

  <div class="detail-body">
    <div class="main-content">
      <div class="tabs">
        <button
          class="tab"
          class:active={activeTab === 'context'}
          onclick={() => (activeTab = 'context')}
        >
          Context
        </button>
        <button
          class="tab"
          class:active={activeTab === 'activity'}
          onclick={() => (activeTab = 'activity')}
          data-pending={pendingClarifications.length > 0 ? pendingClarifications.length : undefined}
        >
          Activity
        </button>
      </div>

      {#if activeTab === 'context'}
        {#if task}
          <div class="tab-content">
            <h3>Description</h3>
            <p class="description">{task.description}</p>
            {#if task.relevant_docs.length > 0}
              <h3>Relevant Docs</h3>
              <ul>
                {#each task.relevant_docs as doc}
                  <li><code>{doc}</code></li>
                {/each}
              </ul>
            {/if}
            {#if task.github_issues.length > 0}
              <h3>GitHub Issues</h3>
              {#each task.github_issues as issue}
                <a
                  href={`https://github.com/scottcm/the-hive/issues/${issue}`}
                  target="_blank"
                  rel="noreferrer noopener"
                  class="gh-link"
                >#{issue} ↗</a>
              {/each}
            {/if}
          </div>
        {:else}
          <p class="loading">Loading task...</p>
        {/if}
      {:else}
        <div class="tab-content">
          {#if task && pendingClarifications.length > 0}
            <h3>Pending Clarifications</h3>
            {#each pendingClarifications as c}
              <div class="clarification">
                <p class="question"><strong>{c.asked_by}:</strong> {c.question}</p>
                <textarea
                  placeholder="Type your answer..."
                  value={answerDrafts[c.id] ?? ''}
                  oninput={(e) => (answerDrafts = { ...answerDrafts, [c.id]: (e.target as HTMLTextAreaElement).value })}
                ></textarea>
                <button onclick={() => submitAnswer(c.id)}>Submit</button>
              </div>
            {/each}
          {/if}

          {#if task && answeredClarifications.length > 0}
            <h3>Answered Clarifications</h3>
            {#each answeredClarifications as c}
              <div class="clarification answered">
                <p class="question"><strong>{c.asked_by}:</strong> {c.question}</p>
                <p class="answer">{c.answer}</p>
              </div>
            {/each}
          {/if}

          {#if task}
            <h3>Notes</h3>
            <div class="notes-list">
              {#each task.notes as note}
                <div class="note">
                  <span class="note-author">{note.author}</span>
                  <span class="note-time">{new Date(note.created_at).toLocaleString()}</span>
                  <p>{note.content}</p>
                </div>
              {/each}
            </div>
          {/if}
          <div class="note-input">
            <input
              class="author-input"
              placeholder="Your name"
              bind:value={noteAuthor}
            />
            <input
              placeholder="Add a note..."
              bind:value={newNote}
            />
            <button onclick={postNote}>Post</button>
          </div>
        </div>
      {/if}
    </div>

    <aside class="sidebar">
      {#if task}
        <div class="sidebar-field">
          <label for="status-select">Status</label>
          <select
            id="status-select"
            value={task.status}
            onchange={(e) => updateField('status', (e.target as HTMLSelectElement).value)}
          >
            <option value="open">open</option>
            <option value="in_progress">in progress</option>
            <option value="blocked">blocked</option>
            <option value="done">done</option>
            <option value="cancelled">cancelled</option>
            <option value="superseded">superseded</option>
          </select>
        </div>
        <div class="sidebar-field">
          <label for="assignee-input">Assignee</label>
          <input
            id="assignee-input"
            type="text"
            value={task.assigned_to ?? ''}
            placeholder="unassigned"
            onchange={(e) => updateField('assigned_to', (e.target as HTMLInputElement).value)}
          />
        </div>
        <div class="sidebar-field">
          <span class="field-label">Milestone</span>
          <span>{task.milestone_name}</span>
        </div>
        {#if task.tags.length > 0}
          <div class="sidebar-field">
            <span class="field-label">Tags</span>
            <div class="tags">
              {#each task.tags as tag}
                <span class="tag">{tag}</span>
              {/each}
            </div>
          </div>
        {/if}
        {#if (task.blocked_by ?? []).length > 0}
          <div class="sidebar-field">
            <span class="field-label">Blocked by</span>
            {#each task.blocked_by as dep}
              <a href={`/tasks/${dep.id}`} class="dep-link">
                <span class="dep-status status-{dep.status}"></span>#{dep.id} {dep.title}
              </a>
            {/each}
          </div>
        {/if}
        {#if (task.blocks ?? []).length > 0}
          <div class="sidebar-field">
            <span class="field-label">Blocks</span>
            {#each task.blocks as dep}
              <a href={`/tasks/${dep.id}`} class="dep-link">
                <span class="dep-status status-{dep.status}"></span>#{dep.id} {dep.title}
              </a>
            {/each}
          </div>
        {/if}
      {/if}
    </aside>
  </div>
</div>

<style>
  .task-detail { max-width: 1100px; margin: 0 auto; padding: 24px; }

  .detail-header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }
  .back-link { color: #58a6ff; text-decoration: none; font-size: 13px; }
  .back-link:hover { text-decoration: underline; }
  .task-id-badge { font-size: 13px; color: #8b949e; font-family: monospace; }
  .task-title { font-size: 20px; font-weight: 600; color: #f0f6fc; margin: 0; }

  .detail-body { display: grid; grid-template-columns: 1fr 280px; gap: 24px; }

  .tabs { display: flex; gap: 4px; border-bottom: 1px solid #30363d; margin-bottom: 16px; }
  .tab { background: none; border: none; padding: 8px 16px; color: #8b949e; cursor: pointer; font-size: 14px; border-bottom: 2px solid transparent; }
  .tab.active { color: #f0f6fc; border-bottom-color: #f0883e; }
  .tab:hover { color: #c9d1d9; }
  .tab[data-pending]::after { content: " (" attr(data-pending) ")"; font-size: 11px; color: #f85149; }

  .tab-content h3 { font-size: 13px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 8px; }
  .description { color: #c9d1d9; font-size: 14px; line-height: 1.6; }

  .clarification { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px; margin-bottom: 12px; }
  .clarification.answered { opacity: 0.7; }
  .question { color: #e1e4e8; margin: 0 0 8px; }
  .answer { color: #8b949e; font-style: italic; margin: 0; }
  textarea { width: 100%; background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; border-radius: 4px; padding: 8px; font-size: 13px; resize: vertical; min-height: 60px; box-sizing: border-box; }

  .notes-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
  .note { background: #161b22; border: 1px solid #21262d; border-radius: 6px; padding: 12px; }
  .note-author { font-size: 12px; font-weight: 600; color: #58a6ff; }
  .note-time { font-size: 11px; color: #6e7681; margin-left: 8px; }
  .note-input { display: flex; gap: 8px; }
  .note-input input { flex: 1; background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; border-radius: 4px; padding: 8px; font-size: 13px; }
  .note-input .author-input { flex: 0 0 120px; }

  button { padding: 6px 14px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; font-size: 13px; cursor: pointer; }
  button:hover { background: #30363d; }

  .sidebar { display: flex; flex-direction: column; gap: 16px; }
  .sidebar-field { display: flex; flex-direction: column; gap: 4px; }
  .sidebar-field label, .sidebar-field .field-label { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
  .sidebar-field select, .sidebar-field input[type="text"] { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 8px; border-radius: 4px; font-size: 13px; }
  .dep-link { display: flex; align-items: center; gap: 6px; color: #58a6ff; text-decoration: none; font-size: 13px; margin-bottom: 2px; }
  .dep-link:hover { text-decoration: underline; }
  .dep-status { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dep-status.status-open { background: #3fb950; }
  .dep-status.status-in_progress { background: #58a6ff; }
  .dep-status.status-blocked { background: #f85149; }
  .dep-status.status-done { background: #6e7681; }

  .status { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 12px; display: inline-block; }
  .status-open { background: #1a3a2a; color: #3fb950; }
  .status-in_progress { background: #1a2d4a; color: #58a6ff; }
  .status-blocked { background: #3d1a1a; color: #f85149; }
  .status-done { background: #1a1a2e; color: #8b949e; }

  .tags { display: flex; flex-wrap: wrap; gap: 4px; }
  .tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: #1a2d4a; color: #58a6ff; }

  .gh-link { color: #58a6ff; font-size: 13px; text-decoration: none; margin-right: 8px; }
  .gh-link:hover { text-decoration: underline; }

  .loading { color: #8b949e; font-style: italic; }
</style>
