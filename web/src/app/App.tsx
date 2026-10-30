import { Route, Routes } from 'react-router-dom';
import type { ApiClient } from '../api/client';
import { CameraScreen } from '../screens/CameraScreen';
import { ClipDetailScreen } from '../screens/ClipDetailScreen';
import { FindFootageScreen } from '../screens/FindFootageScreen';
import { NotFoundScreen } from '../screens/NotFoundScreen';
import { SavedClipsScreen } from '../screens/SavedClipsScreen';
import { ZonesScreen } from '../screens/ZonesScreen';
import { ApiClientProvider } from './ApiContext';
import { AppDataProvider } from './AppDataContext';
import { AppShell } from './AppShell';
import { SavedClipsProvider } from './SavedClipsContext';
import { SearchProvider } from './SearchContext';
import { SelectedDayProvider } from './SelectedDayContext';

/** The whole app for one API client. The router comes from outside (BrowserRouter, or MemoryRouter in tests). */
export function App({ client }: { client: ApiClient }) {
  return (
    <ApiClientProvider client={client}>
      <AppDataProvider>
        <SelectedDayProvider>
          <SavedClipsProvider>
            <SearchProvider>
              <Routes>
                <Route element={<AppShell />}>
                  <Route index element={<FindFootageScreen />} />
                  <Route path="camera" element={<CameraScreen />} />
                  <Route path="clip/:id" element={<ClipDetailScreen />} />
                  <Route path="zones" element={<ZonesScreen />} />
                  <Route path="saved" element={<SavedClipsScreen />} />
                  <Route path="*" element={<NotFoundScreen />} />
                </Route>
              </Routes>
            </SearchProvider>
          </SavedClipsProvider>
        </SelectedDayProvider>
      </AppDataProvider>
    </ApiClientProvider>
  );
}
