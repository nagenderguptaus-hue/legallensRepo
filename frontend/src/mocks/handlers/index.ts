import { chatHandlers } from './chat';
import { conversationHandlers } from './conversations';
import { documentHandlers } from './documents';
import { systemHandlers } from './system';

export const handlers = [
  ...conversationHandlers,
  ...documentHandlers,
  ...chatHandlers,
  ...systemHandlers,
];
