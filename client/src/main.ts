import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

import { init, use } from '@fe-sentry/core';
import PerformancePlugin from '@fe-sentry/performance';
import ScreenRecordPlugin from '@fe-sentry/screen-record';

init({ dsn: 'http://127.0.0.1:8080/api/log' });
use(PerformancePlugin);
use(ScreenRecordPlugin);

bootstrapApplication(App, appConfig).catch((err) => console.error(err));
