import { getServerApi } from "@/lib/api.server";
import type { LessonStatusResponse } from "./upload.service";

export interface ListLessonsParams {
    limit?: number;
    offset?: number;
}

export const lessonsService = {
    listLessons: async ({ limit = 20, offset = 0 }: ListLessonsParams = {}): Promise<LessonStatusResponse[]> => {
        const api = await getServerApi();
        const { data } = await api.get<LessonStatusResponse[]>("content/lessons", { params: { limit, offset } });
        return data;
    },
};
