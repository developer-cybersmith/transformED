import { BookDetail } from "@/components/dashboard/books/BookDetail";

// Next 16.2.9 / React 19.2.4: a dynamic route's `params` is a Promise and must
// be awaited. Signature copied from app/lesson/[id]/page.tsx, which is the
// verified in-repo shape. The page itself stays a server component and hands
// the id to a client component -- everything that FETCHES must be client-side,
// because api.ts's auth interceptor is browser-only.
export default async function BookDetailPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = await params;

    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 pb-24">
            <BookDetail bookId={id} />
        </div>
    );
}
