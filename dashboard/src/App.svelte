<script lang="ts">
  import { onMount } from 'svelte';
  import Board from './lib/Board.svelte';
  import TaskDetail from './lib/TaskDetail.svelte';

  type Route =
    | { name: 'board' }
    | { name: 'task-detail'; taskId: number }
    | { name: 'not-found' };

  function parseRoute(path: string): Route {
    const taskMatch = path.match(/^\/tasks\/(\d+)/);
    if (taskMatch) return { name: 'task-detail', taskId: Number(taskMatch[1]) };
    if (path === '/' || path === '') return { name: 'board' };
    return { name: 'not-found' };
  }

  let route: Route = $state(parseRoute(window.location.pathname));

  function navigate(path: string) {
    window.history.pushState({}, '', path);
    route = parseRoute(path);
  }

  onMount(() => {
    const onPop = () => { route = parseRoute(window.location.pathname); };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  });

  function handleClick(e: MouseEvent) {
    const anchor = (e.target as Element)?.closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href');
    if (!href || href.startsWith('http') || href.startsWith('//') || href.startsWith('#')) return;
    e.preventDefault();
    navigate(href);
  }
</script>

<svelte:window onclick={handleClick} />

{#if route.name === 'board'}
  <Board />
{:else if route.name === 'task-detail'}
  <TaskDetail taskId={route.taskId} />
{:else}
  <div class="not-found">
    <h2>Page not found</h2>
    <a href="/">← Back to board</a>
  </div>
{/if}

<style>
  :global(body) {
    margin: 0;
    padding: 0;
    background: #0f1117;
  }

  .not-found {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 60vh;
    color: #8b949e;
    gap: 16px;
  }

  .not-found h2 {
    color: #f0f6fc;
    margin: 0;
  }

  .not-found a {
    color: #58a6ff;
    text-decoration: none;
  }

  .not-found a:hover {
    text-decoration: underline;
  }
</style>
