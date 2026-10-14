import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalPayload, approvalState } from '../src/approval.js';
const pending = { id: '2', metadata: { approval_required: true, approval_id: 'token' } };
test('approval is bound to persisted message and exact token', () => {
  assert.deepEqual(approvalPayload(pending, 's', false), { session_id: 's', message_id: 2, approval_id: 'token', approved: false });
});
test('processing, failed and obsolete cards cannot replay', () => {
  for (const message of [{ ...pending, turnStatus: 'processing' }, { ...pending, turnStatus: 'failed' }, { ...pending, id: 'stream-x' }, { ...pending, metadata: { approval_required: true } }]) {
    assert.throws(() => approvalPayload(message, 's', true));
  }
  assert.equal(approvalState({ ...pending, turnStatus: 'failed' }), 'failed');
});
import { rememberedSession } from '../src/approval.js';
test('refresh restores only the same account and backend session', () => {
  const saved = JSON.stringify({ sessionId: 's', apiBase: 'base', subject: 'one', tenant: 'tenant' });
  assert.equal(rememberedSession(saved, 'base', {subject: 'one', tenant_id: 'tenant'}), 's');
  assert.equal(rememberedSession(saved, 'base', {subject: 'other', tenant_id: 'tenant'}), '');
  assert.equal(rememberedSession(saved, 'other-base', {subject: 'one', tenant_id: 'tenant'}), '');
  assert.equal(rememberedSession('bad JSON', 'base', {}), '');
});
test('ordinary failed or processing chat turns are not approvals', () => {
  assert.equal(approvalState({ role: 'user', turnStatus: 'failed' }), null);
  assert.equal(approvalState({ role: 'user', turnStatus: 'processing' }), null);
});
