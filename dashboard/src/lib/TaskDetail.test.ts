import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import TaskDetail from './TaskDetail.svelte';

describe('Task Detail View', () => {
  const mockTask = {
    id: 2,
    title: 'Wire salience scoring into stage 4',
    description: 'Integrate the salience service scoring into pipeline stage 4.',
    status: 'blocked',
    assignee: 'codex',
    milestone_id: 10,
    milestone_name: 'Phase 3 — System Design',
    tags: ['orchestrator', 'salience'],
    sequence_order: 2,
    github_issues: [143, 147],
    relevant_docs: ['docs/design/ORCHESTRATOR_EVENT_PIPELINE.md'],
    created_at: '2026-03-04T10:30:00Z',
    updated_at: '2026-03-04T15:15:00Z',
    notes: [
      { id: 1, author: 'scott', content: 'Created task.', created_at: '2026-03-04T10:30:00Z' }
    ],
    clarifications: [
      { id: 1, asked_by: 'codex', question: 'Sync or async?', answer: null, status: 'pending', created_at: '2026-03-04T12:00:00Z' }
    ]
  };

  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.resetMocks();
  });

  it('renders task details and tabs', async () => {
    fetchMock.mockResponse(async (req) => {
      if (req.url.endsWith('/api/tasks/2')) {
        return JSON.stringify(mockTask);
      }
      return JSON.stringify([]);
    });

    render(TaskDetail, { taskId: 2 });

    await waitFor(() => {
      expect(screen.getByText('Wire salience scoring into stage 4')).toBeInTheDocument();
      expect(screen.getByText('#2')).toBeInTheDocument();
      expect(screen.getByText('Context')).toBeInTheDocument();
      expect(screen.getByText('Activity')).toBeInTheDocument();
    });
  });

  it('switches between Context and Activity tabs', async () => {
    fetchMock.mockResponse(JSON.stringify(mockTask));

    render(TaskDetail, { taskId: 2 });

    await waitFor(() => expect(screen.getByText('Description')).toBeInTheDocument());
    
    const activityTab = screen.getByText(/Activity/i);
    await fireEvent.click(activityTab);

    expect(screen.getByText('Notes')).toBeInTheDocument();
    expect(screen.queryByText('Description')).not.toBeInTheDocument();
  });

  it('shows pending clarifications in Activity tab', async () => {
    fetchMock.mockResponse(JSON.stringify(mockTask));

    render(TaskDetail, { taskId: 2 });

    const activityTab = screen.getByText(/Activity/i);
    await fireEvent.click(activityTab);

    await waitFor(() => {
      expect(screen.getByText('Sync or async?')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Type your answer...')).toBeInTheDocument();
    });
  });

  it('can post a new note', async () => {
    fetchMock.mockResponse(async (req) => {
        if (req.method === 'POST' && req.url.endsWith('/api/tasks/2/notes')) {
            return JSON.stringify({ id: 2, author: 'scott', content: 'New note', created_at: new Date().toISOString() });
        }
        return JSON.stringify(mockTask);
    });

    render(TaskDetail, { taskId: 2 });

    const activityTab = screen.getByText(/Activity/i);
    await fireEvent.click(activityTab);

    const input = screen.getByPlaceholderText('Add a note...');
    await fireEvent.input(input, { target: { value: 'New note' } });
    
    const postBtn = screen.getByText('Post');
    await fireEvent.click(postBtn);

    expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/tasks/2/notes'),
        expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ content: 'New note' })
        })
    );
  });
});
