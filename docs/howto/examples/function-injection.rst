.. meta::
   :description: diwire function injection examples with Container.inject and Injected[T].

Function injection
==================

Basic ``@container.inject`` usage
---------------------------------

Demonstrates how to mark function parameters with ``Injected[T]`` and decorate
the function with ``@container.inject``.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container, Injected


   @dataclass
   class EmailService:
       smtp_host: str = "smtp.example.com"

       def send(self, to: str, subject: str) -> str:
           return f"Email sent to {to}: {subject} (via {self.smtp_host})"


   container = Container()
   container.register_instance(EmailService, instance=EmailService("mail.company.com"))


   @container.inject
   def send_welcome_email(
       user_email: str,
       user_name: str,
       email_service: Injected[EmailService],
   ) -> str:
       return email_service.send(user_email, f"Welcome, {user_name}!")


   print(send_welcome_email(user_email="alice@example.com", user_name="Alice"))

Advanced: resolver propagation (internal detail)
------------------------------------------------

Inject wrappers accept an internal kwarg ``__diwire_resolver``.
Generated resolver code passes it only when invoking providers decorated with
``@container.inject`` so scoped dependencies resolve against the active scope.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container, Injected, Lifetime, Scope


   @dataclass
   class RequestSession:
       request_id: int


   @dataclass
   class Handler:
       session: RequestSession


   container = Container()
   container.register_factory(
       RequestSession,
       factory=lambda: RequestSession(request_id=1),
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )


   @container.inject
   def build_handler(session: Injected[RequestSession]) -> Handler:
       return Handler(session=session)


   container.register_factory(
       Handler,
       factory=build_handler,
       scope=Scope.REQUEST,
       lifetime=Lifetime.SCOPED,
   )

   with container.enter_scope() as request_scope:
       handler = request_scope.resolve(Handler)
       print(handler.session.request_id)

Read more
---------

- :doc:`../../core/function-injection`
- :doc:`../../core/scopes`
