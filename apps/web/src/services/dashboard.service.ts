import { dashboardApi } from '../mocks/api';

export const dashboardService = {
    getDashboard: () => dashboardApi.getDashboardData(),
};
