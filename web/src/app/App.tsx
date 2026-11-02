import { Navigate, Route, Routes } from 'react-router-dom';
import type { ApiClient } from '../api/client';
import { CameraRecordingsScreen } from '../screens/CameraRecordingsScreen';
import { CamerasScreen } from '../screens/CamerasScreen';
import { ClipDetailScreen } from '../screens/ClipDetailScreen';
import { FindFootageScreen } from '../screens/FindFootageScreen';
import { NotFoundScreen } from '../screens/NotFoundScreen';
import { RecordingPlayerScreen } from '../screens/RecordingPlayerScreen';
import { SavedClipsScreen } from '../screens/SavedClipsScreen';
import { WelcomeScreen } from '../screens/WelcomeScreen';
import { ZonesScreen } from '../screens/ZonesScreen';
import { ApiClientProvider } from './ApiContext';
import { AppDataProvider } from './AppDataContext';
import { AppShell } from './AppShell';
import { SavedClipsProvider } from './SavedClipsContext';
import { SearchProvider } from './SearchContext';
import { SelectedDayProvider } from './SelectedDayContext';
import { ToastProvider } from './ToastContext';

/** The whole app for one API client. The router comes from outside (BrowserRouter, or MemoryRouter in tests). */
export function App({ client }: { client: ApiClient }) {
  return (
    <ApiClientProvider client={client}>
      <ToastProvider>
        <AppDataProvider>
          <SelectedDayProvider>
            <SavedClipsProvider>
              <SearchProvider>
                <Routes>
                  {/* The welcome page has its own top bar and width, so it sits outside the app shell. */}
                  <Route path="welcome" element={<WelcomeScreen />} />
                  <Route element={<AppShell />}>
                    <Route index element={<FindFootageScreen />} />
                    <Route path="cameras" element={<CamerasScreen />} />
                    <Route path="cameras/:id/recordings" element={<CameraRecordingsScreen />} />
                    {/* The old address of the recordings screen. */}
                    <Route path="camera" element={<Navigate to="/cameras" replace />} />
                    <Route path="clip/:id" element={<ClipDetailScreen />} />
                    <Route path="recordings/:id" element={<RecordingPlayerScreen />} />
                    <Route path="zones" element={<ZonesScreen />} />
                    <Route path="saved" element={<SavedClipsScreen />} />
                    <Route path="*" element={<NotFoundScreen />} />
                  </Route>
                </Routes>
              </SearchProvider>
            </SavedClipsProvider>
          </SelectedDayProvider>
        </AppDataProvider>
      </ToastProvider>
    </ApiClientProvider>
  );
}
