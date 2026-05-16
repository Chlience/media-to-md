import { useEffect, useState } from 'react';
import { AdminPage } from './pages/AdminPage';
import { WorkbenchPage } from './pages/WorkbenchPage';
import { useWorkbenchTasks } from './services/workbenchTasks';

export function getHashRoute(hash = window.location.hash): 'admin' | 'workbench' {
  return hash === '#/admin' ? 'admin' : 'workbench';
}

export function App() {
  const [route, setRoute] = useState(() => getHashRoute());
  const workbench = useWorkbenchTasks();

  useEffect(() => {
    const onHashChange = () => setRoute(getHashRoute());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return route === 'admin' ? <AdminPage /> : <WorkbenchPage workbench={workbench} />;
}
