import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { Spinner } from '@/components/ui/spinner'
import { Toaster } from '@/components/ui/toast'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Shell } from './components/Shell'
import { ToastProvider } from './components/ui'
import { ApiError, useMe } from './lib/api'
import { AbTest } from './pages/AbTest'
import { Config } from './pages/Config'
import { Dashboard } from './pages/Dashboard'
import { Live } from './pages/Live'
import { Settings } from './pages/Settings'
import { SetupNeeded, SignIn } from './pages/SignIn'
import { Strategy } from './pages/Strategy'

const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 } },
})

function Gate() {
  const me = useMe()
  if (me.isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-background text-muted-foreground">
        <Spinner className="size-5 text-muted-foreground" />
      </div>
    )
  }
  if (me.error instanceof ApiError) {
    if (me.error.status === 401) return <SignIn />
    if (me.error.status === 503) return <SetupNeeded message={me.error.message} />
  }
  if (me.error) return <SetupNeeded message={me.error.message} />
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="live" element={<Live />} />
        <Route path="ab-test" element={<AbTest />} />
        <Route path="config" element={<Config />} />
        <Route path="strategy" element={<Strategy />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Toaster>
          <ToastProvider>
            <BrowserRouter>
              <Gate />
            </BrowserRouter>
          </ToastProvider>
        </Toaster>
      </TooltipProvider>
    </QueryClientProvider>
  )
}
