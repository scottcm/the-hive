import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import Board from './Board.svelte';

describe('Board View', () => {
  const projectOneMilestones = [
    { id: 10, project_id: 1, name: 'Board UX', description: 'Main board implementation', status: 'open' },
    { id: 11, project_id: 1, name: 'Completed Work', description: 'Shipped tasks', status: 'done' }
  ];

  const projectTwoMilestones = [
    { id: 20, project_id: 2, name: 'API Sync', description: 'Second project milestone', status: 'open' }
  ];

  const tasksByMilestone: Record<number, unknown[]> = {
    10: [
      {
        id: 100,
        milestone_id: 10,
        title: 'Implement board filters',
        description: 'Support filter state in UI',
        status: 'in_progress',
        assigned_to: 'scott',
        tags: ['dashboard'],
        sequence_order: 1,
        github_issues: [42]
      },
      {
        id: 101,
        milestone_id: 10,
        title: 'Wire milestone API',
        description: 'Load milestones and tasks',
        status: 'open',
        assigned_to: 'gemini',
        tags: ['mcp'],
        sequence_order: 2,
        github_issues: []
      }
    ],
    11: [
      {
        id: 102,
        milestone_id: 11,
        title: 'Shipped done task',
        description: 'Already completed',
        status: 'done',
        assigned_to: null,
        tags: ['dashboard'],
        sequence_order: 3,
        github_issues: []
      }
    ],
    20: [
      {
        id: 200,
        milestone_id: 20,
        title: 'Project beta task',
        description: 'Other project task',
        status: 'open',
        assigned_to: 'codex',
        tags: ['orchestrator'],
        sequence_order: 1,
        github_issues: [77]
      }
    ]
  };

  function setupFetchMocks(pendingCount = 3) {
    fetchMock.mockResponse(async (req) => {
      const url = new URL(req.url, 'http://localhost');

      if (url.pathname === '/api/projects') {
        return JSON.stringify([
          { id: 1, name: 'Project Alpha', description: '', status: 'active' },
          { id: 2, name: 'Project Beta', description: '', status: 'active' }
        ]);
      }

      if (url.pathname === '/api/clarifications/pending-count') {
        return JSON.stringify({ count: pendingCount });
      }

      if (url.pathname === '/api/milestones') {
        const projectId = Number(url.searchParams.get('project_id'));
        if (projectId === 1) return JSON.stringify(projectOneMilestones);
        if (projectId === 2) return JSON.stringify(projectTwoMilestones);
      }

      if (url.pathname === '/api/tasks') {
        const milestoneId = Number(url.searchParams.get('milestone_id'));
        return JSON.stringify(tasksByMilestone[milestoneId] ?? []);
      }

      return JSON.stringify([]);
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.resetMocks();
  });

  it('renders project selector and header actions', async () => {
    setupFetchMocks();

    render(Board);

    await waitFor(() => {
      expect(screen.getByText('Project Alpha')).toBeInTheDocument();
      expect(screen.getByText('Project Beta')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '+ Project' })).toBeInTheDocument();
    });
  });

  it('renders clarification banner when count > 0', async () => {
    setupFetchMocks(3);

    render(Board);

    await waitFor(() => {
      expect(screen.getByText(/3 pending clarifications/i)).toBeInTheDocument();
    });
  });

  it('loads tasks by milestone_id and links each card to task detail', async () => {
    setupFetchMocks();

    render(Board);

    await waitFor(() => {
      expect(screen.getByText('Board UX')).toBeInTheDocument();
      expect(screen.getByText('Implement board filters')).toBeInTheDocument();
      expect(screen.getByText('#100')).toBeInTheDocument();
    });

    const taskCalls = fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/tasks'));
    expect(taskCalls.length).toBeGreaterThan(0);
    taskCalls.forEach(([input]) => {
      expect(String(input)).toContain('milestone_id=');
      expect(String(input)).not.toContain('project_id=');
    });

    const taskCardLink = screen.getByRole('link', { name: /Implement board filters/i });
    expect(taskCardLink).toHaveAttribute('href', '/tasks/100');
  });

  it('filters by assignee using assigned_to payload field', async () => {
    setupFetchMocks();

    render(Board);

    await waitFor(() => {
      expect(screen.getByText('Implement board filters')).toBeInTheDocument();
      expect(screen.getByText('Wire milestone API')).toBeInTheDocument();
    });

    const assigneeSelect = screen.getByLabelText('Assignee:');
    await fireEvent.change(assigneeSelect, { target: { value: 'scott' } });

    await waitFor(() => {
      expect(screen.getByText('Implement board filters')).toBeInTheDocument();
      expect(screen.queryByText('Wire milestone API')).not.toBeInTheDocument();
    });
  });

  it('defaults done milestones to collapsed and toggles open', async () => {
    setupFetchMocks();

    render(Board);

    await waitFor(() => {
      expect(screen.getByText('Completed Work')).toBeInTheDocument();
    });

    expect(screen.queryByText('Shipped done task')).not.toBeInTheDocument();

    const doneMilestoneHeader = screen.getByRole('button', { name: /Completed Work/i });
    await fireEvent.click(doneMilestoneHeader);

    await waitFor(() => {
      expect(screen.getByText('Shipped done task')).toBeInTheDocument();
    });
  });
});
