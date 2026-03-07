import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, beforeEach } from 'vitest';
import App from './App.svelte';

const mockTask = {
  id: 42,
  title: 'Route test task',
  description: 'A task for routing tests',
  status: 'open',
  assigned_to: null,
  milestone_id: 1,
  milestone_name: 'Test Milestone',
  tags: [],
  sequence_order: 1,
  github_issues: [],
  relevant_docs: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  notes: [],
  clarifications: []
};

function setupDefaultMocks() {
  fetchMock.mockResponse(async (req) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/api/projects') return JSON.stringify([{ id: 1, name: 'Project Alpha', description: '', status: 'active' }]);
    if (url.pathname === '/api/clarifications/pending-count') return JSON.stringify({ count: 0 });
    if (url.pathname === '/api/milestones') return JSON.stringify([]);
    if (url.pathname === '/api/tasks') return JSON.stringify([]);
    if (url.pathname === `/api/tasks/${mockTask.id}`) return JSON.stringify(mockTask);
    return JSON.stringify([]);
  });
}

describe('App routing', () => {
  beforeEach(() => {
    fetchMock.resetMocks();
    window.history.pushState({}, '', '/');
  });

  it('renders Board at /', async () => {
    setupDefaultMocks();
    render(App);

    await waitFor(() => {
      expect(screen.getByText('The Hive')).toBeInTheDocument();
    });
  });

  it('renders TaskDetail at /tasks/:id', async () => {
    window.history.pushState({}, '', `/tasks/${mockTask.id}`);
    setupDefaultMocks();
    render(App);

    await waitFor(() => {
      expect(screen.getByText('Route test task')).toBeInTheDocument();
      expect(screen.getByText(`#${mockTask.id}`)).toBeInTheDocument();
    });
  });

  it('navigates to task detail when a board task link is clicked', async () => {
    fetchMock.mockResponse(async (req) => {
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname === '/api/projects') return JSON.stringify([{ id: 1, name: 'Alpha', description: '', status: 'active' }]);
      if (url.pathname === '/api/clarifications/pending-count') return JSON.stringify({ count: 0 });
      if (url.pathname === '/api/milestones') return JSON.stringify([{ id: 10, project_id: 1, name: 'M1', description: '', status: 'open' }]);
      if (url.pathname === '/api/tasks' && url.searchParams.get('milestone_id') === '10') {
        return JSON.stringify([{ id: 42, milestone_id: 10, title: 'Route test task', description: '', status: 'open', assigned_to: null, tags: [], sequence_order: 1, github_issues: [] }]);
      }
      if (url.pathname === `/api/tasks/${mockTask.id}`) return JSON.stringify(mockTask);
      return JSON.stringify([]);
    });

    render(App);

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Route test task/i })).toBeInTheDocument();
    });

    const link = screen.getByRole('link', { name: /Route test task/i });
    await fireEvent.click(link);

    await waitFor(() => {
      expect(screen.getByText('Route test task')).toBeInTheDocument();
      expect(screen.getByText('#42')).toBeInTheDocument();
      expect(window.location.pathname).toBe('/tasks/42');
    });
  });

  it('navigates back to board via back link from task detail', async () => {
    window.history.pushState({}, '', `/tasks/${mockTask.id}`);
    setupDefaultMocks();
    render(App);

    await waitFor(() => {
      expect(screen.getByText('Route test task')).toBeInTheDocument();
    });

    const backLink = screen.getByRole('link', { name: /board/i });
    await fireEvent.click(backLink);

    await waitFor(() => {
      expect(screen.getByText('The Hive')).toBeInTheDocument();
      expect(window.location.pathname).toBe('/');
    });
  });

  it('renders 404 state for unknown routes', async () => {
    window.history.pushState({}, '', '/unknown/path');
    setupDefaultMocks();
    render(App);

    await waitFor(() => {
      expect(screen.getByText(/not found/i)).toBeInTheDocument();
    });
  });
});
