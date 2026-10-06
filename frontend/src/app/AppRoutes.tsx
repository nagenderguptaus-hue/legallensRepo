import { Route, Routes } from 'react-router';
import { ChatRoute } from '@/features/chat/ChatRoute';
import { NotFoundPage } from '@/features/system/NotFoundPage';
import { AppShell } from './AppShell';

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ChatRoute />} />
        <Route path="c/:conversationId" element={<ChatRoute />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
