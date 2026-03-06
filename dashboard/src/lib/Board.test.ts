import { render, screen, waitFor } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import Board from './Board.svelte';

describe('Board View', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.resetMocks();
  });

  it('renders project selector and fetches projects', async () => {
    fetchMock.mockResponse(async (req) => {
      if (req.url.endsWith('/api/projects')) {
        return JSON.stringify([{ id: 1, name: 'Project Alpha' }]);
      }
      return JSON.stringify([]);
    });

    render(Board);

    await waitFor(() => {
      expect(screen.getByText('Project Alpha')).toBeInTheDocument();
    });
  });

  it('renders clarification banner when count > 0', async () => {
    fetchMock.mockResponse(async (req) => {
      if (req.url.endsWith('/api/clarifications/pending-count')) {
        return JSON.stringify({ count: 3 });
      }
      return JSON.stringify([]);
    });

    render(Board);

    await waitFor(() => {
      expect(screen.getByText(/3 pending clarifications/i)).toBeInTheDocument();
    });
  });

  it('renders milestones and tasks for selected project', async () => {
    fetchMock.mockResponse(async (req) => {
      if (req.url.includes('/api/projects')) {
        return JSON.stringify([{ id: 1, name: 'Project Alpha' }]);
      }
      if (req.url.includes('/api/milestones')) {
        return JSON.stringify([{ id: 10, project_id: 1, name: 'Milestone 1', description: 'Desc 1', status: 'open' }]);
      }
      if (req.url.includes('/api/tasks')) {
        return JSON.stringify([{ id: 100, milestone_id: 10, title: 'Task 1', status: 'open', tags: ['mcp'], assignee: 'scott' }]);
      }
      return JSON.stringify([]);
    });

    render(Board);

    await waitFor(() => {
      expect(screen.getByText('Milestone 1')).toBeInTheDocument();
      expect(screen.getByText('Task 1')).toBeInTheDocument();
      expect(screen.getByText('#100')).toBeInTheDocument();
    });
  });
});
