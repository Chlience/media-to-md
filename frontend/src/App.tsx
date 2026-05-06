import { useEffect, useState } from 'react';
import { AdminPage } from './pages/AdminPage';
import { WorkbenchPage } from './pages/WorkbenchPage';

export function getHashRoute(hash = window.location.hash): 'admin' | 'workbench' {
  return hash === '#/admin' ? 'admin' : 'workbench';
}

export function App() {
  const [route, setRoute] = useState(() => getHashRoute());

  useEffect(() => {
    const onHashChange = () => setRoute(getHashRoute());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return route === 'admin' ? <AdminPage /> : <WorkbenchPage />;
}
