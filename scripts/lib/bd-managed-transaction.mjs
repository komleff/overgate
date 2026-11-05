// Одна durable queue → один опубликованный snapshot+outcomes. Новые inputs не примешиваются.
import { canonical, validateQueue, planReplay, replayHandles, validateBlockingGraph } from './bd-managed-contract.mjs';
import { parseSnapshot } from './bd-snapshot.mjs';
import { openJournal, saveJournal, assertBootstrapQueue } from './bd-managed-journal.mjs';
import { executeBatch } from './bd-managed-cli.mjs';
import { ZERO } from './bd-managed-git.mjs';

const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
export function runTransaction({ repository, directory, intents, acknowledgement, materialize }) {
  validateQueue(intents.map(canonical).join('\n'));
  let journal = openJournal(directory, intents), mutations = 0;
  const anchor = acknowledgement.base === ZERO ? null : acknowledgement.base;
  let state = repository.readPublished(anchor);
  const finish = () => {
    journal = saveJournal(directory, { ...journal, phase: 'published', published: state.R });
    const byId = new Map(parseSnapshot(state.snapshot).map(({ record }) => [record.id, record]));
    const outcomes = intents.map(intent => state.ledger.outcomes.find(outcome => outcome.intent.intent_id === intent.intent_id));
    const claims = outcomes.filter(outcome => outcome.intent.op === 'claim').map(outcome => {
      const row = byId.get(outcome.result.ref);
      return { id: outcome.result.ref, actor: outcome.intent.actor, status: row?.status ?? null, assignee: row?.assignee ?? null,
        confirmed: row?.status === 'in_progress' && row.assignee === outcome.intent.actor };
    });
    return { status: 'published', published_sha: state.R, queue_hash: journal.queue_hash, mutations,
      outcomes: outcomes.map(({ intent, payload_hash, result }) => ({ intent_id: intent.intent_id, payload_hash, result })), claims };
  };
  const pendingError = reason => {
    const error = new Error(`pending publication: ${reason}; retry the SAME prepared queue (zero new CLI mutations when R unchanged)`);
    error.code = 'PENDING_PUBLICATION'; error.summary = { status: 'pending', queue_hash: journal.queue_hash, candidate: journal.candidate, base: journal.current_base };
    return error;
  };
  while (true) {
    assertBootstrapQueue(acknowledgement, intents, state.ledger, directory);
    requireThat(intents[0].base === ZERO || state.history?.includes(intents[0].base), 'prepared queue base is not in retained published history');
    const rows = parseSnapshot(state.snapshot).map(({ record }) => record), plan = planReplay(intents, rows, state.ledger);
    if (plan.pending.length === 0 && plan.conflicts.length === 0) return finish();
    requireThat(journal.phase !== 'published', 'published journal outcomes missing from shared ledger; refuse downgrade');
    if (plan.conflicts.length) {
      journal = saveJournal(directory, { ...journal, phase: 'conflict', conflicts: plan.conflicts, conflict_base: state.R });
      const error = new Error('precondition conflict retained: prepare reviewed resolution with NEW op IDs and use --resolve <queue_hash> <newqueue>');
      error.code = 'PRECONDITION_CONFLICT'; error.conflicts = plan.conflicts; throw error;
    }
    requireThat(journal.phase !== 'conflict', 'terminal conflict retained: use --resolve with reviewed new prepared queue');
    if (!journal.candidate || state.R !== journal.current_base) {
      if (journal.candidate) {
        if (journal.attempts >= 2) {
          journal = saveJournal(directory, { ...journal, phase: 'conflict', conflict_base: state.R, conflicts: [{ field: '$retry_limit', actual: state.R }] });
          throw new Error('bounded replay conflict: candidate/input retained; use --resolve after reviewing current R');
        }
        // Сохраняем parent старого candidate до готовности нового; restart не должен
        // принять старый candidate за результат materialization нового R.
        journal = saveJournal(directory, { ...journal, attempts: journal.attempts + 1 });
      }
      const handles = replayHandles(intents, state.ledger);
      validateBlockingGraph(rows, plan.pending, handles);
      const store = materialize(state.snapshot, intents[0].actor);
      let result;
      try { result = executeBatch(store, intents, state.ledger); }
      catch (error) {
        // Private частичное выполнение не публикуется; сохраняем input и даём
        // явный resolution route вместо невосстановимого prepared состояния.
        journal = saveJournal(directory, { ...journal, phase: 'conflict', conflict_base: state.R,
          conflicts: [{ field: '$cli_execution', actual: error.message }] });
        const retained = new Error(`CLI batch conflict retained (${error.message}); use --resolve with reviewed new op IDs`);
        retained.code = 'PRECONDITION_CONFLICT'; retained.conflicts = journal.conflicts; throw retained;
      }
      mutations += result.mutations;
      const candidate = repository.commitCandidate({ base: state.R, snapshot: result.snapshot, ledger: result.ledger });
      repository.pinCandidate(candidate, journal.queue_hash);
      journal = saveJournal(directory, { ...journal, phase: 'pending', current_base: state.R, candidate });
    }
    let pushError;
    try { repository.pushCandidate(journal.candidate); } catch (error) { pushError = error; }
    let next;
    try { next = repository.readPublished(anchor); }
    catch (error) { throw pendingError(`readback unavailable (${error.message}); candidate is durable`); }
    if (next.R === state.R) {
      if (pushError) throw pendingError(pushError.message);
      throw pendingError('push returned success but published ref did not confirm candidate');
    }
    state = next;
    // Shared outcomes сначала: lost push receipt не повторяет уже опубликованный batch.
  }
}
