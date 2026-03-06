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
    assignee: string | null;
    tags: string[];
    sequence_order: number;
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

  async function fetchData(url: string) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch ${url}`);
    return res.json();
  }

  async function loadProjects() {
    const data = await fetchData('/api/projects');
    projects = data;
    if (projects.length > 0 && selectedProjectId === null) {
      selectedProjectId = projects[0].id;
    }
  }

  async function loadClarificationsCount() {
    const data = await fetchData('/api/clarifications/pending-count');
    pendingClarificationsCount = data.count;
  }

  async function loadBoardData() {
    if (!selectedProjectId) return;
    const [ms, ts] = await Promise.all([
      fetchData(`/api/milestones?project_id=${selectedProjectId}`),
      fetchData(`/api/tasks?project_id=${selectedProjectId}`)
    ]);
    milestones = ms;
    tasks = ts;

    // Default collapse completed milestones
    milestones.forEach(m => {
        if (m.status === 'done') {
            collapsedMilestones.add(m.id);
        }
    });
  }

  onMount(() => {
    loadProjects();
    loadClarificationsCount();
  });

  $effect(() => {
    if (selectedProjectId) {
      loadBoardData();
    }
  });

  function toggleMilestone(id: number) {
    if (collapsedMilestones.has(id)) {
      collapsedMilestones.delete(id);
    } else {
      collapsedMilestones.add(id);
    }
  }

  let filteredTasks = $derived(tasks.filter(t => {
    if (filters.status !== 'All' && t.status !== filters.status.toLowerCase().replace(' ', '_')) return false;
    if (filters.assignee !== 'All') {
        if (filters.assignee === 'Unassigned' && t.assignee !== null) return false;
        if (filters.assignee !== 'Unassigned' && t.assignee !== filters.assignee.toLowerCase()) return false;
    }
    if (filters.tag !== 'All' && !t.tags.includes(filters.tag.toLowerCase())) return false;
    return true;
  }));

  function getTasksByMilestone(milestoneId: number) {
    return filteredTasks.filter(t => t.milestone_id === milestoneId);
  }

  const allTags = $derived([...new Set(tasks.flatMap(t => t.tags))]);
  const allAssignees = $derived([...new Set(tasks.map(t => t.assignee).filter(Boolean))]);

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
      <div class="milestone-header" onclick={() => toggleMilestone(milestone.id)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && toggleMilestone(milestone.id)}>
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
            <span class="task-title">{task.title}
              {#each task.tags as tag}
                <span class="tag {tag}">{tag}</span>
              {/each}
            </span>
            <span class="status status-{task.status}">{task.status.replace('_', ' ')}</span>
            <span class="assignee" class:unassigned={!task.assignee}>
              {#if task.assignee}
                <span class="assignee-dot {task.assignee}"></span> {task.assignee}
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

  .tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: #1a2d4a; color: #58a6ff; font-weight: 500; text-transform: lowercase; }
  .tag.orchestrator { background: #2a1d0e; color: #f0883e; }
  .tag.dashboard { background: #1a3a2a; color: #3fb950; }

  .status { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 12px; text-align: center; text-transform: uppercase; letter-spacing: 0.5px; }
  .status-open { background: #1a3a2a; color: #3fb950; }
  .status-in_progress { background: #1a2d4a; color: #58a6ff; }
  .status-blocked { background: #3d1a1a; color: #f85149; }
  .status-done { background: #1a1a2e; color: #8b949e; }

  .assignee { font-size: 12px; color: #c9d1d9; display: flex; align-items: center; gap: 4px; }
  .assignee-dot { width: 8px; height: 8px; border-radius: 50%; }
  .assignee-dot.scott { background: #f0883e; }
  .unassigned { color: #6e7681; font-style: italic; }

  .blocked-badge { display: inline-flex; align-items: center; justify-content: center; background: #f85149; color: #0f1117; width: 14px; height: 14px; border-radius: 50%; font-size: 10px; font-weight: 700; }
</style>
