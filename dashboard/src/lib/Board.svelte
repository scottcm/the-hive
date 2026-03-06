<script lang="ts">
  import { onMount } from 'svelte';

  interface Project {
    id: number;
    name: string;
    description: string;
    status: string;
  }

  interface Milestone {
    id: number;
    project_id: number;
    name: string;
    description: string;
    status: string;
  }

  interface Task {
    id: number;
    milestone_id: number;
    title: string;
    description: string;
    status: string;
    assigned_to: string | null;
    tags: string[];
    sequence_order: number;
    github_issues: number[];
  }

  let projects: Project[] = $state([]);
  let selectedProjectId: number | null = $state(null);
  let milestones: Milestone[] = $state([]);
  let tasks: Task[] = $state([]);
  let pendingClarificationsCount = $state(0);
  let filters = $state({
    status: 'All',
    assignee: 'All',
    tag: 'All'
  });

  let collapsedMilestones: Set<number> = $state(new Set());

  async function fetchData<T>(url: string): Promise<T> {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch ${url}`);
    return (await res.json()) as T;
  }

  async function loadProjects(): Promise<void> {
    const data = await fetchData<Project[]>('/api/projects');
    projects = data;
    if (projects.length > 0 && selectedProjectId === null) {
      selectedProjectId = projects[0].id;
    }
  }

  async function loadClarificationsCount(): Promise<void> {
    const data = await fetchData<{ count: number }>('/api/clarifications/pending-count');
    pendingClarificationsCount = data.count;
  }

  async function loadBoardData(projectId: number): Promise<void> {
    const ms = await fetchData<Milestone[]>(`/api/milestones?project_id=${projectId}`);
    const taskResponses = await Promise.all(
      ms.map((milestone) => fetchData<Task[]>(`/api/tasks?milestone_id=${milestone.id}`))
    );
    const loadedTasks = taskResponses
      .flat()
      .sort((a, b) => a.sequence_order - b.sequence_order || a.id - b.id);

    // Prevent stale updates if the project selection changes mid-fetch.
    if (selectedProjectId !== projectId) {
      return;
    }

    milestones = ms;
    tasks = loadedTasks;
    collapsedMilestones = new Set(
      milestones.filter((milestone) => milestone.status === 'done').map((milestone) => milestone.id)
    );
  }

  onMount(() => {
    void loadProjects();
    void loadClarificationsCount();
  });

  $effect(() => {
    if (selectedProjectId !== null) {
      void loadBoardData(selectedProjectId);
    }
  });

  function toggleMilestone(id: number) {
    const next = new Set(collapsedMilestones);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    collapsedMilestones = next;
  }

  let filteredTasks = $derived(tasks.filter(t => {
    const statusMap: Record<string, string> = {
      Open: 'open',
      'In Progress': 'in_progress',
      Blocked: 'blocked',
      Done: 'done'
    };

    if (filters.status !== 'All' && t.status !== statusMap[filters.status]) return false;
    if (filters.assignee !== 'All') {
        if (filters.assignee === 'Unassigned' && t.assigned_to !== null) return false;
        if (filters.assignee !== 'Unassigned' && t.assigned_to !== filters.assignee) return false;
    }
    if (filters.tag !== 'All' && !t.tags.includes(filters.tag)) return false;
    return true;
  }));

  function getTasksByMilestone(milestoneId: number) {
    return filteredTasks.filter(t => t.milestone_id === milestoneId);
  }

  const allTags = $derived([...new Set(tasks.flatMap(t => t.tags))]);
  const allAssignees = $derived(
    [...new Set(tasks.map((t) => t.assigned_to).filter((assignee): assignee is string => Boolean(assignee)))]
  );

</script>

<div class="header">
  <div class="header-left">
    <h1><span>&#x2B22;</span> The Hive</h1>
    <select bind:value={selectedProjectId} class="project-selector" aria-label="Project selector">
      {#each projects as project}
        <option value={project.id}>{project.name}</option>
      {/each}
    </select>
  </div>
  <div class="header-actions">
    <button class="btn">+ Project</button>
    <button class="btn">+ Milestone</button>
    <button class="btn btn-primary">+ Task</button>
  </div>
</div>

{#if pendingClarificationsCount > 0}
<div class="clarification-banner">
  <strong>{pendingClarificationsCount} pending clarifications</strong> — agents are blocked and waiting for answers
  <button class="btn">Review</button>
</div>
{/if}

<div class="filter-bar">
  <label>
    Status:
    <select bind:value={filters.status}>
      <option>All</option>
      <option>Open</option>
      <option>In Progress</option>
      <option>Blocked</option>
      <option>Done</option>
    </select>
  </label>
  <label>
    Assignee:
    <select bind:value={filters.assignee}>
      <option>All</option>
      {#each allAssignees as assignee}
          <option>{assignee}</option>
      {/each}
      <option>Unassigned</option>
    </select>
  </label>
  <label>
    Tag:
    <select bind:value={filters.tag}>
      <option>All</option>
      {#each allTags as tag}
          <option>{tag}</option>
      {/each}
    </select>
  </label>
  <div class="stats">
    <strong>{filteredTasks.length}</strong> tasks
  </div>
</div>

<div class="board">
  {#each milestones as milestone}
    <div class="milestone" class:milestone-done={milestone.status === 'done'}>
      <div
        class="milestone-header"
        onclick={() => toggleMilestone(milestone.id)}
        role="button"
        tabindex="0"
        onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && toggleMilestone(milestone.id)}
      >
        <span class="milestone-toggle" class:collapsed={collapsedMilestones.has(milestone.id)}>&#x25BC;</span>
        <span class="milestone-name">{milestone.name}</span>
        <span class="milestone-desc">{milestone.description}</span>
        <div class="milestone-counts">
          <span>{getTasksByMilestone(milestone.id).length} tasks</span>
        </div>
      </div>
      {#if !collapsedMilestones.has(milestone.id)}
      <div class="task-list">
        {#each getTasksByMilestone(milestone.id) as task}
          <div class="task-card">
            <span class="task-id">#{task.id}</span>
            <span class="task-title">
              <a class="task-detail-link" href={`/tasks/${task.id}`}>{task.title}</a>
              {#each task.tags as tag}
                <span class="tag {tag}">{tag}</span>
              {/each}
              {#each task.github_issues as issue}
                <a
                  class="gh-link"
                  href={`https://github.com/scottcm/the-hive/issues/${issue}`}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  #{issue} &#x2197;
                </a>
              {/each}
            </span>
            <span class="status status-{task.status}">{task.status.replace('_', ' ')}</span>
            <span class="assignee" class:unassigned={!task.assigned_to}>
              {#if task.assigned_to}
                <span class="assignee-dot {task.assigned_to}"></span> {task.assigned_to}
              {:else}
                unassigned
              {/if}
            </span>
            {#if task.status === 'blocked'}
              <span class="blocked-badge">!</span>
            {:else}
              <span></span>
            {/if}
            <span></span>
          </div>
        {/each}
      </div>
      {/if}
    </div>
  {/each}
</div>

<style>
  /* Base styles adapted from mockup */
  :global(body) { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e1e4e8; margin: 0; }

  .header { display: flex; align-items: center; justify-content: space-between; padding: 12px 24px; background: #161b22; border-bottom: 1px solid #30363d; }
  .header-left { display: flex; align-items: center; gap: 16px; }
  .header h1 { font-size: 18px; font-weight: 600; color: #f0f6fc; margin: 0; }
  .header h1 span { color: #f0883e; }
  .project-selector { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 8px; border-radius: 4px; font-size: 14px; }
  .header-actions { display: flex; gap: 8px; }

  .btn { padding: 6px 14px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; font-size: 13px; cursor: pointer; }
  .btn:hover { background: #30363d; }
  .btn-primary { background: #238636; border-color: #238636; color: #fff; }
  .btn-primary:hover { background: #2ea043; }

  .clarification-banner { display: flex; align-items: center; gap: 8px; margin: 16px 24px 0; padding: 10px 14px; background: #2a1515; border: 1px solid #4a2020; border-radius: 6px; font-size: 13px; color: #f85149; }
  .clarification-banner strong { color: #f0f6fc; }
  .clarification-banner .btn { margin-left: auto; font-size: 12px; }

  .filter-bar { display: flex; align-items: center; gap: 12px; padding: 10px 24px; background: #161b22; border-bottom: 1px solid #30363d; font-size: 13px; flex-wrap: wrap; margin-top: 16px; }
  .filter-bar label { color: #8b949e; }
  .filter-bar select { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 4px 8px; border-radius: 4px; font-size: 13px; }
  .stats { margin-left: auto; color: #8b949e; }
  .stats strong { color: #f0883e; }

  .board { padding: 20px 24px; }

  .milestone { margin-bottom: 24px; }
  .milestone-done { opacity: 0.6; }
  .milestone-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #21262d; cursor: pointer; user-select: none; }
  .milestone-header:hover { border-bottom-color: #388bfd; }
  .milestone-toggle { font-size: 12px; color: #8b949e; transition: transform 0.15s; }
  .milestone-toggle.collapsed { transform: rotate(-90deg); }
  .milestone-name { font-size: 15px; font-weight: 600; color: #f0f6fc; }
  .milestone-desc { font-size: 12px; color: #8b949e; }
  .milestone-counts { margin-left: auto; font-size: 12px; color: #8b949e; }

  .task-list { display: flex; flex-direction: column; gap: 4px; }
  .task-card { display: grid; grid-template-columns: 40px 1fr 120px 100px 30px 30px; align-items: center; gap: 12px; padding: 10px 14px; background: #161b22; border: 1px solid #21262d; border-radius: 6px; cursor: pointer; transition: border-color 0.15s; color: inherit; }
  .task-card:hover { border-color: #388bfd; }
  .task-id { font-size: 12px; color: #8b949e; font-family: monospace; }
  .task-title { font-size: 14px; color: #e1e4e8; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .task-detail-link { color: inherit; text-decoration: none; }
  .task-detail-link:hover { text-decoration: underline; }
  .gh-link { color: #388bfd; font-size: 12px; text-decoration: none; }
  .gh-link:hover { text-decoration: underline; }

  .tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: #1a2d4a; color: #58a6ff; font-weight: 500; text-transform: lowercase; }
  .tag.orchestrator { background: #2a1d0e; color: #f0883e; }
  .tag.mcp { background: #2a2a1a; color: #d2a8ff; }
  .tag.dashboard { background: #1a3a2a; color: #3fb950; }

  .status { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 12px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; }
  .status-open { background: #1a3a2a; color: #3fb950; }
  .status-in_progress { background: #1a2d4a; color: #58a6ff; }
  .status-blocked { background: #3d1a1a; color: #f85149; }
  .status-done { background: #1a1a2e; color: #8b949e; }

  .assignee { font-size: 12px; color: #c9d1d9; display: flex; align-items: center; gap: 4px; }
  .assignee-dot { width: 8px; height: 8px; border-radius: 50%; background: #58a6ff; }
  .assignee-dot.claude { background: #a371f7; }
  .assignee-dot.codex { background: #3fb950; }
  .assignee-dot.gemini { background: #388bfd; }
  .assignee-dot.scott { background: #f0883e; }
  .unassigned { color: #6e7681; font-style: italic; }

  .blocked-badge { display: inline-flex; align-items: center; justify-content: center; background: #f85149; color: #0f1117; width: 14px; height: 14px; border-radius: 50%; font-size: 10px; font-weight: 700; }
</style>
